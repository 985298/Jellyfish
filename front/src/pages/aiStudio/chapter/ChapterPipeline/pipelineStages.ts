// Pipeline execution logic for the ChapterPipeline feature (P2.4).
//
// Each stage is independently runnable: it tracks its own task id(s), polls for
// progress, and reports an output count (e.g. "生成了 8 张图片") back to the
// UI. The "一键开始" button chains all stages sequentially via `runAll`.
//
// All API contracts mirror the original ChapterPipeline.tsx implementation; the
// only behavioral change is per-stage progress + output tracking and retry on
// failure.

import { message } from 'antd'
import { FilmService } from '../../../../services/generated'
import type { StageKey, StageOutput, StagePatch } from './types'

const API_BASE = '/api/v1/studio'

/* eslint-disable @typescript-eslint/no-explicit-any */
// Task result payloads are intentionally typed as `any` because the backend
// returns free-form dicts (script division JSON, asset lists, render result)
// that the pipeline forwards verbatim to downstream endpoints.

/** Functions the stage runners need from the host component. */
export type PipelineCtx = {
  projectId: string | undefined
  chapterId: string | undefined
  scriptText: string
  setLoading: (v: boolean) => void
  updateStage: (key: StageKey, patch: StagePatch) => void
  resetStageForRun: (key: StageKey) => void
  poll: (taskId: string, onTick: (progress: number, status: string) => void) => Promise<{ status: string; progress: number }>
  rememberTaskId?: (key: StageKey, taskId: string | null) => void
}

export type ExecResult = { ok: boolean; output?: StageOutput; error?: string; taskId?: string | null }

function clamp(n: number): number {
  return Math.max(0, Math.min(100, Math.round(n)))
}

/** POST to an endpoint and extract data.task_id from the standard envelope. */
async function postForTaskId(url: string, body: unknown): Promise<string | null> {
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const json = await r.json()
    return json?.data?.task_id ?? json?.data?.id ?? null
  } catch {
    return null
  }
}

/** Fetch the result payload for a task (best-effort; returns null on failure). */
async function fetchTaskResult(taskId: string): Promise<any | null> {
  try {
    const r = await FilmService.getTaskResultApiV1FilmTasksTaskIdResultGet({ taskId })
    return (r as any)?.data ?? null
  } catch {
    return null
  }
}

/** Find the latest succeeded task of a given kind and return its result. */
async function findSucceededTaskResult(taskKind: string): Promise<any | null> {
  try {
    const r = await fetch(`/api/v1/film/tasks?task_kind=${taskKind}&page=1&page_size=5`)
    const data = (await r.json())?.data
    const items = data?.items || []
    const succeeded = items.find((t: any) => t.status === 'succeeded')
    if (!succeeded) return null
    return await fetchTaskResult(succeeded.id)
  } catch {
    return null
  }
}

/** Poll one task id, routing progress ticks to the stage state. */
async function pollOne(
  ctx: PipelineCtx,
  taskId: string,
  onTick: (progress: number) => void,
): Promise<'succeeded' | 'failed' | 'cancelled' | 'timeout'> {
  const result = await ctx.poll(taskId, (progress) => onTick(progress))
  if (result.status === 'succeeded') return 'succeeded'
  if (result.status === 'timeout') return 'timeout'
  if (result.status === 'cancelled') return 'cancelled'
  return 'failed'
}

async function runAssetExtract(ctx: PipelineCtx): Promise<ExecResult> {
  const { projectId, scriptText } = ctx
  if (!projectId || !scriptText) return { ok: false, error: '缺少项目或剧本文本' }
  ctx.setLoading(true)
  ctx.resetStageForRun('asset_extract')
  try {
    const tid = await postForTaskId('/api/v1/script-processing/asset-extract-async', {
      project_id: projectId,
      script_text: scriptText,
    })
    if (!tid) throw new Error('No task_id')
    ctx.rememberTaskId?.('asset_extract', tid)
    let progress = 5
    const outcome = await pollOne(ctx, tid, (p) => {
      progress = Math.max(progress, p)
      ctx.updateStage('asset_extract', { progress: clamp(progress), status: 'running' })
    })
    if (outcome !== 'succeeded') throw new Error(outcome === 'timeout' ? '任务超时' : '任务未成功')

    let charCount = 0
    try {
      const r = await fetch(`/api/v1/studio/entities/character?project_id=${projectId}`)
      const data = await r.json()
      const items = data?.data?.items || data?.items || []
      charCount = Array.isArray(items) ? items.length : 0
    } catch {
      charCount = 0
    }
    const output: StageOutput = { count: charCount, label: '个资产' }
    ctx.updateStage('asset_extract', { status: 'done', progress: 100, output })
    return { ok: true, output, taskId: tid }
  } catch (e: any) {
    const error = e?.message || '提取失败'
    ctx.updateStage('asset_extract', { status: 'failed', error })
    return { ok: false, error, taskId: null }
  } finally {
    ctx.setLoading(false)
  }
}

async function runAssetImages(ctx: PipelineCtx): Promise<ExecResult> {
  const { projectId } = ctx
  if (!projectId) return { ok: false, error: '缺少项目' }
  ctx.setLoading(true)
  ctx.resetStageForRun('asset_images')
  try {
    const r = await fetch(`/api/v1/studio/entities/character?project_id=${projectId}`)
    const charsData = await r.json()
    const chars = charsData?.data?.items || charsData?.items || []
    if (!chars.length) {
      const output: StageOutput = { count: 0, total: 0, label: '张图片', extra: '无角色资产' }
      ctx.updateStage('asset_images', { status: 'done', progress: 100, output })
      return { ok: true, output }
    }
    const total = chars.length
    const taskIds: string[] = []
    for (const char of chars) {
      try {
        const imgR = await fetch(`/api/v1/studio/image-tasks/characters/${char.id}/image-tasks`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            image_id: char.character_images?.[0]?.id || 1,
            prompt: char.description || char.name,
          }),
        })
        const imgData = await imgR.json()
        if (imgData?.data?.task_id) taskIds.push(imgData.data.task_id)
      } catch {
        // skip failed submission
      }
    }
    let completed = 0
    let failed = 0
    const subProgress = (i: number) => Math.round(((i + 1) / total) * 100)
    for (let i = 0; i < taskIds.length; i++) {
      ctx.updateStage('asset_images', {
        progress: Math.max(2, subProgress(i) - 5),
        status: 'running',
      })
      const outcome = await pollOne(ctx, taskIds[i], () => {})
      if (outcome === 'succeeded') completed++
      else failed++
      ctx.updateStage('asset_images', {
        progress: subProgress(i),
        status: 'running',
        output: { count: completed, total, label: '张图片', extra: failed ? `失败 ${failed}` : undefined },
      })
    }
    const output: StageOutput = {
      count: completed,
      total,
      label: '张图片',
      extra: failed ? `失败 ${failed}` : undefined,
    }
    ctx.updateStage('asset_images', { status: 'done', progress: 100, output })
    return { ok: true, output }
  } catch (e: any) {
    const error = e?.message || '生成失败'
    ctx.updateStage('asset_images', { status: 'failed', error })
    return { ok: false, error, taskId: null }
  } finally {
    ctx.setLoading(false)
  }
}

async function runDivide(ctx: PipelineCtx): Promise<ExecResult> {
  const { chapterId, scriptText } = ctx
  if (!chapterId || !scriptText) return { ok: false, error: '缺少章节或剧本文本' }
  ctx.setLoading(true)
  ctx.resetStageForRun('divide')
  try {
    const tid = await postForTaskId('/api/v1/script-processing/divide-async', {
      script_text: scriptText,
      write_to_db: true,
      chapter_id: chapterId,
    })
    if (!tid) throw new Error('No task_id')
    ctx.rememberTaskId?.('divide', tid)
    let progress = 5
    const outcome = await pollOne(ctx, tid, (p) => {
      progress = Math.max(progress, p)
      ctx.updateStage('divide', { progress: clamp(progress), status: 'running' })
    })
    if (outcome !== 'succeeded') throw new Error(outcome === 'timeout' ? '任务超时' : '任务未成功')

    let shotCount = 0
    try {
      const r = await fetch(`/api/v1/studio/shots?chapter_id=${chapterId}`)
      const data = await r.json()
      const items = data?.data?.items || data?.items || []
      shotCount = Array.isArray(items) ? items.length : 0
    } catch {
      shotCount = 0
    }
    const output: StageOutput = { count: shotCount, label: '个镜头' }
    ctx.updateStage('divide', { status: 'done', progress: 100, output })
    return { ok: true, output, taskId: tid }
  } catch (e: any) {
    const error = e?.message || '分镜失败'
    ctx.updateStage('divide', { status: 'failed', error })
    return { ok: false, error, taskId: null }
  } finally {
    ctx.setLoading(false)
  }
}

async function runBind(ctx: PipelineCtx): Promise<ExecResult> {
  const { chapterId } = ctx
  if (!chapterId) return { ok: false, error: '缺少章节' }
  ctx.setLoading(true)
  ctx.resetStageForRun('bind_assets')
  try {
    const division = await findSucceededTaskResult('script_divide')
    if (!division) throw new Error('请先完成分镜提取')
    const assets = await findSucceededTaskResult('script_asset_extract')
    if (!assets) throw new Error('请先完成资产提取')
    const divisionData = division?.result || division
    const tid = await postForTaskId('/api/v1/script-processing/bind-assets-async', {
      chapter_id: chapterId,
      script_division_json: JSON.stringify(divisionData),
      asset_list_json: JSON.stringify(assets),
    })
    if (!tid) throw new Error('No task_id')
    ctx.rememberTaskId?.('bind_assets', tid)
    let progress = 5
    const outcome = await pollOne(ctx, tid, (p) => {
      progress = Math.max(progress, p)
      ctx.updateStage('bind_assets', { progress: clamp(progress), status: 'running' })
    })
    if (outcome !== 'succeeded') throw new Error(outcome === 'timeout' ? '任务超时' : '任务未成功')

    let bindCount = 0
    try {
      const r = await fetch(`${API_BASE}/chapters/${chapterId}/pipeline-status`)
      const data = (await r.json())?.data || {}
      bindCount = Number(data?.bind_count ?? 0)
    } catch {
      bindCount = 0
    }
    const output: StageOutput = { count: bindCount, label: '条绑定' }
    ctx.updateStage('bind_assets', { status: 'done', progress: 100, output })
    return { ok: true, output, taskId: tid }
  } catch (e: any) {
    const error = e?.message || '绑定失败'
    ctx.updateStage('bind_assets', { status: 'failed', error })
    return { ok: false, error, taskId: null }
  } finally {
    ctx.setLoading(false)
  }
}

async function runKeyframes(ctx: PipelineCtx): Promise<ExecResult> {
  const { chapterId } = ctx
  if (!chapterId) return { ok: false, error: '缺少章节' }
  ctx.setLoading(true)
  ctx.resetStageForRun('keyframes')
  try {
    const r = await fetch(`/api/v1/studio/shots?chapter_id=${chapterId}`)
    const shotsData = await r.json()
    const shots = shotsData?.data?.items || shotsData?.items || []
    if (!shots.length) {
      const output: StageOutput = { count: 0, total: 0, label: '张帧图', extra: '无镜头' }
      ctx.updateStage('keyframes', { status: 'done', progress: 100, output })
      return { ok: true, output }
    }
    const total = shots.length
    const taskIds: string[] = []
    for (const shot of shots) {
      try {
        const fr = await fetch(`/api/v1/studio/image-tasks/shot/${shot.id}/frame-image-tasks`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ frame_type: 'first', model_id: null }),
        })
        const fd = await fr.json()
        if (fd?.data?.task_id) taskIds.push(fd.data.task_id)
      } catch {
        // skip
      }
    }
    let completed = 0
    let failed = 0
    const subProgress = (i: number) => Math.round(((i + 1) / total) * 100)
    for (let i = 0; i < taskIds.length; i++) {
      ctx.updateStage('keyframes', {
        progress: Math.max(2, subProgress(i) - 5),
        status: 'running',
      })
      const outcome = await pollOne(ctx, taskIds[i], () => {})
      if (outcome === 'succeeded') completed++
      else failed++
      ctx.updateStage('keyframes', {
        progress: subProgress(i),
        status: 'running',
        output: { count: completed, total, label: '张帧图', extra: failed ? `失败 ${failed}` : undefined },
      })
    }
    const output: StageOutput = {
      count: completed,
      total,
      label: '张帧图',
      extra: failed ? `失败 ${failed}` : undefined,
    }
    ctx.updateStage('keyframes', { status: 'done', progress: 100, output })
    return { ok: true, output }
  } catch (e: any) {
    const error = e?.message || '生成失败'
    ctx.updateStage('keyframes', { status: 'failed', error })
    return { ok: false, error, taskId: null }
  } finally {
    ctx.setLoading(false)
  }
}

async function runVideos(ctx: PipelineCtx): Promise<ExecResult> {
  const { chapterId } = ctx
  if (!chapterId) return { ok: false, error: '缺少章节' }
  ctx.setLoading(true)
  ctx.resetStageForRun('videos')
  try {
    const r = await fetch(`/api/v1/studio/shots?chapter_id=${chapterId}`)
    const shotsData = await r.json()
    const shots = shotsData?.data?.items || shotsData?.items || []
    if (!shots.length) {
      const output: StageOutput = { count: 0, total: 0, label: '个视频', extra: '无镜头' }
      ctx.updateStage('videos', { status: 'done', progress: 100, output })
      return { ok: true, output }
    }
    const total = shots.length
    const taskIds: string[] = []
    for (const shot of shots) {
      try {
        const vr = await fetch('/api/v1/film/tasks/video', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            shot_id: shot.id,
            reference_mode: 'text_only',
            ratio: '16:9',
            prompt: shot.title || 'scene',
          }),
        })
        const vd = await vr.json()
        if (vd?.data?.task_id) taskIds.push(vd.data.task_id)
      } catch {
        // skip
      }
    }
    let completed = 0
    let failed = 0
    const subProgress = (i: number) => Math.round(((i + 1) / total) * 100)
    for (let i = 0; i < taskIds.length; i++) {
      ctx.updateStage('videos', {
        progress: Math.max(2, subProgress(i) - 5),
        status: 'running',
      })
      const outcome = await pollOne(ctx, taskIds[i], () => {})
      if (outcome === 'succeeded') completed++
      else failed++
      ctx.updateStage('videos', {
        progress: subProgress(i),
        status: 'running',
        output: { count: completed, total, label: '个视频', extra: failed ? `失败 ${failed}` : undefined },
      })
    }
    const output: StageOutput = {
      count: completed,
      total,
      label: '个视频',
      extra: failed ? `失败 ${failed}` : undefined,
    }
    ctx.updateStage('videos', { status: 'done', progress: 100, output })
    return { ok: true, output }
  } catch (e: any) {
    const error = e?.message || '生成失败'
    ctx.updateStage('videos', { status: 'failed', error })
    return { ok: false, error, taskId: null }
  } finally {
    ctx.setLoading(false)
  }
}

async function runRender(ctx: PipelineCtx): Promise<ExecResult> {
  const { chapterId } = ctx
  if (!chapterId) return { ok: false, error: '缺少章节' }
  ctx.setLoading(true)
  ctx.resetStageForRun('render')
  try {
    const r = await fetch(`/api/v1/film/chapters/${chapterId}/render`, { method: 'POST' })
    const json = await r.json().catch(() => ({}))
    if (!r.ok) {
      const detail = (json as any)?.detail || `HTTP ${r.status}`
      throw new Error(typeof detail === 'string' ? detail : '渲染失败')
    }
    const result = (json as any) || {}
    const shotCount = Number(result?.shots_processed ?? result?.results?.length ?? 0)
    const finalUrl = result?.final_url || undefined
    const output: StageOutput = {
      count: shotCount,
      label: '个镜头已配音',
      url: typeof finalUrl === 'string' ? finalUrl : undefined,
    }
    ctx.updateStage('render', { status: 'done', progress: 100, output })
    return { ok: true, output }
  } catch (e: any) {
    const error = e?.message || '渲染失败'
    ctx.updateStage('render', { status: 'failed', error })
    return { ok: false, error, taskId: null }
  } finally {
    ctx.setLoading(false)
  }
}

export type StageRunner = () => Promise<ExecResult>

/** Build a map of stage-key -> runner. Each runner handles its own message toast + chaining. */
export function buildStageRunners(
  ctx: PipelineCtx,
  opts: {
    onLoading?: (content: string) => void
    onSuccess?: (content: string) => void
    onError?: (content: string) => void
    chainNext?: (key: StageKey) => Promise<void>
  } = {},
): Record<StageKey, StageRunner> {
  const onLoading = (content: string) =>
    opts.onLoading?.(content) ?? message.loading({ content, key: 'pipe', duration: 0 })
  const onSuccess = (content: string) =>
    opts.onSuccess?.(content) ?? message.success({ content, key: 'pipe' })
  const onError = (content: string) =>
    opts.onError?.(content) ?? message.error({ content, key: 'pipe' })

  const wrap = (
    label: string,
    fn: (ctx: PipelineCtx) => Promise<ExecResult>,
    next?: StageKey,
  ): StageRunner => async () => {
    onLoading(`${label}中...`)
    const res = await fn(ctx)
    if (res.ok) {
      const o = res.output
      const countText = o
        ? o.total
          ? `${label}完成 ${o.count ?? 0}/${o.total}`
          : `${label}完成 ${o.count ?? 0} ${o.label || ''}`.trim()
        : `${label}完成`
      onSuccess(countText)
      if (next && opts.chainNext) await opts.chainNext(next)
    } else {
      onError(res.error || `${label}失败`)
    }
    return res
  }

  return {
    asset_extract: wrap('资产提取', runAssetExtract, 'asset_images'),
    asset_images: wrap('资产图片', runAssetImages, 'divide'),
    divide: wrap('分镜提取', runDivide, 'bind_assets'),
    bind_assets: wrap('资产绑定', runBind, 'keyframes'),
    keyframes: wrap('帧图生成', runKeyframes, 'videos'),
    videos: wrap('视频生成', runVideos, 'render'),
    render: wrap('章节渲染', runRender),
  }
}

/** Ordered list of stage keys, used by runAll to drive sequential execution. */
export const STAGE_ORDER: StageKey[] = [
  'asset_extract',
  'asset_images',
  'divide',
  'bind_assets',
  'keyframes',
  'videos',
  'render',
]
