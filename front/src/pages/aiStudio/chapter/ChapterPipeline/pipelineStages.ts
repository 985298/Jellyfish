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
import type { StageKey, StageOutput, StageOutputFailedItem, StagePatch } from './types'

/** 单个展开任务：记下它属于哪个实体，才能在轮询后知道具体哪一项失败 */
type Submission = { id: string; label: string; taskId: string }

/** Runner 可选的入参：onlyIds 用于「仅重试失败项」 */
export type RunOptions = { onlyIds?: string[] }

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
  /** 当前阶段是否已被请求中止（中止中段 for-loop 使用） */
  shouldAbort?: (key: StageKey) => boolean
  /** 记录本阶段已提交的任务 id 列表，供批量 cancel */
  rememberTaskIds?: (key: StageKey, taskIds: string[]) => void
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

/**
 * 串行轮询一批已提交的任务。相比逐内联轮询，这里统一处理：
 * - 中止：每轮开始检查 shouldAbort，命中即跳出且不统计后续为失败
 * - 失败明细：记录具体失败的实体，供「仅重试失败项」使用
 */
async function pollBatch(
  ctx: PipelineCtx,
  key: StageKey,
  submissions: Submission[],
  label: string,
): Promise<{ completed: number; failed: StageOutputFailedItem[]; aborted: boolean }> {
  const failed: StageOutputFailedItem[] = []
  let completed = 0
  let aborted = false
  const total = submissions.length
  const subProgress = (i: number) => Math.round(((i + 1) / Math.max(total, 1)) * 100)
  for (let i = 0; i < total; i += 1) {
    if (ctx.shouldAbort?.(key)) {
      aborted = true
      break
    }
    ctx.updateStage(key, {
      progress: Math.max(2, subProgress(i) - 5),
      status: 'running',
    })
    const outcome = await pollOne(ctx, submissions[i].taskId, () => {})
    if (outcome === 'succeeded') completed += 1
    else failed.push({ id: submissions[i].id, label: submissions[i].label })
    ctx.updateStage(key, {
      progress: subProgress(i),
      status: 'running',
      output: {
        count: completed,
        total,
        label,
        extra: failed.length ? `失败 ${failed.length}` : undefined,
      },
    })
  }
  return { completed, failed, aborted }
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

async function runAssetImages(ctx: PipelineCtx, opts?: RunOptions): Promise<ExecResult> {
  const { projectId } = ctx
  if (!projectId) return { ok: false, error: '缺少项目' }
  ctx.setLoading(true)
  ctx.resetStageForRun('asset_images')
  try {
    const r = await fetch(`/api/v1/studio/entities/character?project_id=${projectId}`)
    const charsData = await r.json()
    const allChars = charsData?.data?.items || charsData?.items || []
    const targets = opts?.onlyIds?.length
      ? allChars.filter((c: any) => opts.onlyIds?.includes(c.id))
      : allChars
    if (!targets.length) {
      const output: StageOutput = { count: 0, total: 0, label: '张图片', extra: '无角色资产' }
      ctx.updateStage('asset_images', { status: 'done', progress: 100, output })
      return { ok: true, output }
    }
    const total = targets.length
    const submissions: Submission[] = []
    for (const char of targets) {
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
        if (imgData?.data?.task_id) {
          submissions.push({ id: char.id, label: char.name || char.id, taskId: imgData.data.task_id })
        }
      } catch {
        // skip failed submission
      }
    }
    ctx.rememberTaskIds?.('asset_images', submissions.map((s) => s.taskId))

    const { completed, failed, aborted } = await pollBatch(ctx, 'asset_images', submissions, '张图片')
    if (aborted) {
      const output: StageOutput = {
        count: completed,
        total,
        label: '张图片',
        extra: '已中止',
        failedItems: failed,
      }
      ctx.updateStage('asset_images', { status: 'partial', progress: Math.min(99, total ? Math.round((completed / total) * 100) : 0), output })
      return { ok: false, error: '已中止该阶段', output }
    }
    const output: StageOutput = {
      count: completed,
      total,
      label: '张图片',
      extra: failed.length ? `失败 ${failed.length}` : undefined,
      failedItems: failed,
    }
    // 一个都没成功才算阶段失败；部分失败标 partial 让后续阶段仍可推进
    const allFailed = completed === 0 && failed.length > 0
    ctx.updateStage('asset_images', { status: allFailed ? 'failed' : 'done', progress: 100, output })
    return { ok: !allFailed, output, error: allFailed ? `全部 ${failed.length} 项失败` : undefined }
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

async function runKeyframes(ctx: PipelineCtx, opts?: RunOptions): Promise<ExecResult> {
  const { chapterId } = ctx
  if (!chapterId) return { ok: false, error: '缺少章节' }
  ctx.setLoading(true)
  ctx.resetStageForRun('keyframes')
  try {
    const r = await fetch(`/api/v1/studio/shots?chapter_id=${chapterId}`)
    const shotsData = await r.json()
    const allShots = shotsData?.data?.items || shotsData?.items || []
    const targets = opts?.onlyIds?.length
      ? allShots.filter((s: any) => opts.onlyIds?.includes(s.id))
      : allShots
    if (!targets.length) {
      const output: StageOutput = { count: 0, total: 0, label: '张帧图', extra: '无镜头' }
      ctx.updateStage('keyframes', { status: 'done', progress: 100, output })
      return { ok: true, output }
    }
    const total = targets.length
    const submissions: Submission[] = []
    for (const shot of targets) {
      try {
        const fr = await fetch(`/api/v1/studio/image-tasks/shot/${shot.id}/frame-image-tasks`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ frame_type: 'first', model_id: null }),
        })
        const fd = await fr.json()
        if (fd?.data?.task_id) {
          submissions.push({ id: shot.id, label: `#${shot.index ?? '镜头'} ${shot.title ?? ''}`.trim(), taskId: fd.data.task_id })
        }
      } catch {
        // skip
      }
    }
    ctx.rememberTaskIds?.('keyframes', submissions.map((s) => s.taskId))

    const { completed, failed, aborted } = await pollBatch(ctx, 'keyframes', submissions, '张帧图')
    const buildOutput = (extra?: string): StageOutput => ({
      count: completed,
      total,
      label: '张帧图',
      extra,
      failedItems: failed,
    })
    if (aborted) {
      const output = buildOutput('已中止')
      ctx.updateStage('keyframes', { status: 'partial', progress: Math.min(99, Math.round((completed / total) * 100)), output })
      return { ok: false, error: '已中止该阶段', output }
    }
    const output = buildOutput(failed.length ? `失败 ${failed.length}` : undefined)
    // 帧图属于可部分失败阶段：只要有成功就让链路继续，失败项留给「仅重试失败项」
    const allFailed = completed === 0 && failed.length > 0
    ctx.updateStage('keyframes', { status: allFailed ? 'failed' : 'done', progress: 100, output })
    return { ok: !allFailed, output, error: allFailed ? `全部 ${failed.length} 项失败` : undefined }
  } catch (e: any) {
    const error = e?.message || '生成失败'
    ctx.updateStage('keyframes', { status: 'failed', error })
    return { ok: false, error, taskId: null }
  } finally {
    ctx.setLoading(false)
  }
}

async function runVideos(ctx: PipelineCtx, opts?: RunOptions): Promise<ExecResult> {
  const { chapterId } = ctx
  if (!chapterId) return { ok: false, error: '缺少章节' }
  ctx.setLoading(true)
  ctx.resetStageForRun('videos')
  try {
    const r = await fetch(`/api/v1/studio/shots?chapter_id=${chapterId}`)
    const shotsData = await r.json()
    const allShots = shotsData?.data?.items || shotsData?.items || []
    const targets = opts?.onlyIds?.length
      ? allShots.filter((s: any) => opts.onlyIds?.includes(s.id))
      : allShots
    if (!targets.length) {
      const output: StageOutput = { count: 0, total: 0, label: '个视频', extra: '无镜头' }
      ctx.updateStage('videos', { status: 'done', progress: 100, output })
      return { ok: true, output }
    }
    const total = targets.length
    const submissions: Submission[] = []
    for (const shot of targets) {
      try {
        const vd = await FilmService.createVideoGenerationTaskApiV1FilmTasksVideoPost({
          requestBody: {
            shot_id: shot.id,
            reference_mode: 'first_frame',
            ratio: '9:16',
            prompt: '',
          },
        })
        if (vd?.data?.task_id) {
          submissions.push({ id: shot.id, label: `#${shot.index ?? '镜头'} ${shot.title ?? ''}`.trim(), taskId: vd.data.task_id })
        }
      } catch {
        // skip
      }
    }
    ctx.rememberTaskIds?.('videos', submissions.map((s) => s.taskId))

    const { completed, failed, aborted } = await pollBatch(ctx, 'videos', submissions, '个视频')
    const buildOutput = (extra?: string): StageOutput => ({
      count: completed,
      total,
      label: '个视频',
      extra,
      failedItems: failed,
    })
    if (aborted) {
      const output = buildOutput('已中止')
      ctx.updateStage('videos', { status: 'partial', progress: Math.min(99, Math.round((completed / total) * 100)), output })
      return { ok: false, error: '已中止该阶段', output }
    }
    const output = buildOutput(failed.length ? `失败 ${failed.length}` : undefined)
    const allFailed = completed === 0 && failed.length > 0
    ctx.updateStage('videos', { status: allFailed ? 'failed' : 'done', progress: 100, output })
    return { ok: !allFailed, output, error: allFailed ? `全部 ${failed.length} 项失败` : undefined }
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

export type StageRunner = (opts?: RunOptions) => Promise<ExecResult>

/** Build a map of stage-key -> runner. Each runner handles its own message toast. */
export function buildStageRunners(
  ctx: PipelineCtx,
  opts: {
    onLoading?: (content: string) => void
    onSuccess?: (content: string) => void
    onError?: (content: string) => void
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
    fn: (ctx: PipelineCtx, opts?: RunOptions) => Promise<ExecResult>,
  ): StageRunner => async (runOpts?: RunOptions) => {
    onLoading(`${label}中...`)
    const res = await fn(ctx, runOpts)
    if (res.ok) {
      const o = res.output
      const countText = o
        ? o.total
          ? `${label}完成 ${o.count ?? 0}/${o.total}`
          : `${label}完成 ${o.count ?? 0} ${o.label || ''}`.trim()
        : `${label}完成`
      onSuccess(countText)
    } else {
      onError(res.error || `${label}失败`)
    }
    return res
  }

  // 注意：这里不再自带后继阶段。链式推进由调用方按 STAGE_ORDER 循环驱动，
  // 否则「继续执行」与 runner 内部递归会互相叠加导致同一阶段跑两遍。
  return {
    asset_extract: wrap('资产提取', runAssetExtract),
    asset_images: wrap('资产图片', runAssetImages),
    divide: wrap('分镜提取', runDivide),
    keyframes: wrap('帧图生成', runKeyframes),
    videos: wrap('视频生成', runVideos),
    render: wrap('章节渲染', runRender),
  }
}

/** Ordered list of stage keys, used by runAll to drive sequential execution. */
export const STAGE_ORDER: StageKey[] = [
  'asset_extract',
  'asset_images',
  'divide',
  'keyframes',
  'videos',
  'render',
]
