// Pipeline execution logic for the ChapterPipeline feature (P2.4).
//
// Each stage is independently runnable: it tracks its own task id(s), polls for
// progress, and reports an output count (e.g. "生成了 8 张图片") back to the
// UI. 链式推进由调用方按 STAGE_ORDER 循环驱动，runner 自身不再递归后继阶段。
//
// All API contracts mirror the original ChapterPipeline.tsx implementation; the
// only behavioral change is per-stage progress + output tracking, batching,
// abort support and retry-on-failed-items.

import { message } from 'antd'
import { FilmService } from '../../../../services/generated'
import type { StageKey, StageOutput, StageOutputFailedItem, StagePatch } from './types'

/** 一批中的单个展开任务：记下它属于哪个实体，轮询后才知道具体哪一项失败 */
type Submission = { id: string; label: string; taskId: string }

/** Runner 可选入参 */
export type RunOptions = {
  /** 只跑这些实体（「仅重试失败项」用） */
  onlyIds?: string[]
  /** 每批并发提交的任务数 */
  batchSize?: number
}

/** 默认每批任务数。后端并发上限为 4，这里取 5 留出余量又不至于堆积太多。 */
const DEFAULT_BATCH_SIZE = 5

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
  /** 当前阶段是否已被请求中止（fan-out 轮询循环使用） */
  shouldAbort?: (key: StageKey) => boolean
  /** 追加记录本阶段已提交的任务 id，供批量 cancel（追加语义） */
  rememberTaskIds?: (key: StageKey, taskIds: string[]) => void
  /** 一批任务共用定时器的并发轮询 */
  pollMany?: (
    entries: TaskPollEntry[],
    onProgress?: (snapshot: PollManySnapshot) => void,
    shouldAbort?: () => boolean,
  ) => Promise<PollManyOutcome>
}

export type TaskPollEntry = { id: string; label: string; taskId: string }
export type PollManySnapshot = {
  completed: number
  failed: number
  cancelled: number
  pending: number
}
export type PollManyOutcome = PollManySnapshot & {
  aborted: boolean
  timedOut: boolean
  failedItems: TaskPollEntry[]
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
 * fan-out 阶段通用骨架（资产图片 / 帧图 / 视频）：
 * - 分批次提交，避免一次性把整章几十个任务同时压给后端
 * - 批内<b>并发</b>轮询：原实现是串行 await 逐个等待，48 个镜头会非常慢
 * - 批次之间与轮询过程中检查中止标志，命中即停止
 * - 记录失败明细，供「仅重试失败项」精准重跑，而不是整章重来
 */
async function runFanOutStage<T extends { id: string }>(
  ctx: PipelineCtx,
  key: StageKey,
  opts: RunOptions | undefined,
  cfg: {
    label: string
    emptyHint: string
    nameOf: (target: T) => string
    loadTargets: () => Promise<T[]>
    submit: (target: T) => Promise<string | null>
  },
): Promise<ExecResult> {
  ctx.setLoading(true)
  ctx.resetStageForRun(key)

  const buildOutput = (
    completed: number,
    total: number,
    failed: StageOutputFailedItem[],
    extra?: string,
  ): StageOutput => ({
    count: completed,
    total,
    label: cfg.label,
    extra,
    failedItems: failed,
  })

  try {
    const all = await cfg.loadTargets()
    const targets = opts?.onlyIds?.length ? all.filter((t) => opts.onlyIds?.includes(t.id)) : all
    const total = targets.length

    if (!total) {
      const output = buildOutput(0, 0, [], cfg.emptyHint)
      ctx.updateStage(key, { status: 'done', progress: 100, output })
      return { ok: true, output }
    }

    const size = Math.max(1, opts?.batchSize ?? DEFAULT_BATCH_SIZE)
    let completed = 0
    let aborted = false
    let timedOut = false
    const failedItems: StageOutputFailedItem[] = []

    for (let start = 0; start < total; start += size) {
      if (ctx.shouldAbort?.(key)) {
        aborted = true
        break
      }

      const chunk = targets.slice(start, start + size)
      const entries: Submission[] = []
      for (const target of chunk) {
        if (ctx.shouldAbort?.(key)) {
          aborted = true
          break
        }
        try {
          const taskId = await cfg.submit(target)
          if (taskId) entries.push({ id: target.id, label: cfg.nameOf(target), taskId })
          else failedItems.push({ id: target.id, label: cfg.nameOf(target) })
        } catch {
          failedItems.push({ id: target.id, label: cfg.nameOf(target) })
        }
      }

      if (entries.length) ctx.rememberTaskIds?.(key, entries.map((entry) => entry.taskId))
      if (aborted || !entries.length) break

      // 批内进度 = 之前批次累计完成 + 本批已完成（含失败/取消，占位推进）
      const onProgress = (snapshot: PollManySnapshot) => {
        const doneInBatch = snapshot.completed + snapshot.failed + snapshot.cancelled
        ctx.updateStage(key, {
          progress: Math.max(2, Math.round(((start + doneInBatch) / total) * 100)),
          status: 'running',
          output: buildOutput(completed + snapshot.completed, total, failedItems),
        })
      }

      const outcome = ctx.pollMany
        ? await ctx.pollMany(
            entries,
            onProgress,
            () => ctx.shouldAbort?.(key) ?? false,
          )
        : await pollManySerially(ctx, key, entries, onProgress)

      completed += outcome.completed
      failedItems.push(...outcome.failedItems)
      if (outcome.aborted) aborted = true
      if (outcome.timedOut) timedOut = true
      if (aborted || timedOut) break
    }

    // 全部失败才算阶段失败；部分失败仍允许后续阶段推进
    const allFailed = completed === 0 && failedItems.length > 0
    const output = buildOutput(
      completed,
      total,
      failedItems,
      aborted ? '已中止' : timedOut ? '超时中断' : failedItems.length ? `失败 ${failedItems.length}` : undefined,
    )
    const status = aborted || timedOut ? 'partial' : allFailed ? 'failed' : 'done'
    ctx.updateStage(key, {
      status,
      progress: allFailed ? 100 : Math.min(99, Math.round((completed / total) * 100)),
      output,
    })
    return {
      ok: !allFailed && !aborted && !timedOut,
      output,
      error: aborted
        ? '已中止该阶段'
        : timedOut
          ? `等待超时（已完成 ${completed}/${total}）`
        : allFailed
          ? `全部 ${failedItems.length} 项失败`
          : undefined,
    }
  } catch (e: any) {
    const error = e?.message || '生成失败'
    ctx.updateStage(key, { status: 'failed', error })
    return { ok: false, error, taskId: null }
  } finally {
    ctx.setLoading(false)
  }
}

/**
 * fan-out 阶段的串行轮询兜底（当宿主未提供 pollMany 时使用）。
 * 仅在「跑一项等一项」的旧行为下使用，新实现应走并发轮询。
 */
async function pollManySerially(
  ctx: PipelineCtx,
  key: StageKey,
  entries: Submission[],
  onProgress?: (snapshot: PollManySnapshot) => void,
): Promise<PollManyOutcome> {
  const failedItems: Submission[] = []
  let completed = 0
  for (let i = 0; i < entries.length; i += 1) {
    if (ctx.shouldAbort?.(key)) {
      return {
        completed,
        failed: failedItems.length,
        cancelled: entries.length - i,
        pending: entries.length - i,
        aborted: true,
        timedOut: false,
        failedItems,
      }
    }
    const outcome = await pollOne(ctx, entries[i].taskId, () => {})
    if (outcome === 'succeeded') completed += 1
    else failedItems.push(entries[i])
    onProgress?.({
      completed,
      failed: failedItems.length,
      cancelled: 0,
      pending: entries.length - (i + 1),
    })
  }
  return {
    completed,
    failed: failedItems.length,
    cancelled: 0,
    pending: 0,
    aborted: false,
    timedOut: false,
    failedItems,
  }
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
  if (!ctx.projectId) return { ok: false, error: '缺少项目' }
  return runFanOutStage(ctx, 'asset_images', opts, {
    label: '张图片',
    emptyHint: '无角色资产',
    nameOf: (c: any) => c.name ?? c.id,
    loadTargets: async () => {
      const r = await fetch(`/api/v1/studio/entities/character?project_id=${ctx.projectId}`)
      const d = await r.json()
      return (d?.data?.items || d?.items || []) as any[]
    },
    submit: async (char: any) => {
      const imgR = await fetch(`/api/v1/studio/image-tasks/characters/${char.id}/image-tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_id: char.character_images?.[0]?.id || 1,
          prompt: char.description || char.name,
      }),
      })
      const imgData = await imgR.json()
      return imgData?.data?.task_id ?? null
    },
  })
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
  return runFanOutStage(ctx, 'keyframes', opts, {
    label: '张帧图',
    emptyHint: '无镜头',
    nameOf: (s: any) => `#${s.index ?? '镜头'} ${s.title ?? ''}`.trim(),
    loadTargets: async () => {
      const r = await fetch(`/api/v1/studio/shots?chapter_id=${chapterId}`)
    const d = await r.json()
      return (d?.data?.items || d?.items || []) as any[]
    },
    submit: async (shot: any) => {
      const fr = await fetch(`/api/v1/studio/image-tasks/shot/${shot.id}/frame-image-tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ frame_type: 'first', model_id: null }),
      })
      const fd = await fr.json()
      return fd?.data?.task_id ?? null
    },
  })
}

async function runVideos(ctx: PipelineCtx, opts?: RunOptions): Promise<ExecResult> {
  const { chapterId } = ctx
  if (!chapterId) return { ok: false, error: '缺少章节' }
  return runFanOutStage(ctx, 'videos', opts, {
    label: '个视频',
    emptyHint: '无镜头',
    nameOf: (s: any) => `#${s.index ?? '镜头'} ${s.title ?? ''}`.trim(),
    loadTargets: async () => {
      const r = await fetch(`/api/v1/studio/shots?chapter_id=${chapterId}`)
      const d = await r.json()
      return (d?.data?.items || d?.items || []) as any[]
    },
    submit: async (shot: any) => {
      const vd = await FilmService.createVideoGenerationTaskApiV1FilmTasksVideoPost({
        requestBody: {
          shot_id: shot.id,
          reference_mode: 'first_frame',
          ratio: '9:16',
          prompt: '',
        },
      })
      return vd?.data?.task_id ?? null
    },
  })
}

async function runRender(ctx: PipelineCtx): Promise<ExecResult> {
  const { chapterId } = ctx
  if (!chapterId) return { ok: false, error: '缺少章节' }
  ctx.setLoading(true)
  ctx.resetStageForRun('render')
  try {
    const json = await fetch(`/api/v1/film/chapters/${chapterId}/render`, { method: 'POST' })
      .then((r) => r.json())
      .catch(() => ({}))
    if (!json || json.detail) {
      throw new Error(typeof json?.detail === 'string' ? json.detail : '渲染失败')
    }
    const result = json.data ?? json ?? {}
    const shotCount = Number(result?.shots_processed ?? result?.results?.length ?? 0)
    const finalUrl = result?.final_url || undefined
    const output: StageOutput = {
      count: shotCount,
      label: '个镜头已配音',
      url: typeof finalUrl === 'string' ? finalUrl : undefined,
    }
    ctx.updateStage('render', { status: 'done', progress: 100, output })
    return { ok: true, output, taskId: null }
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

  // 注意：runner 自带后继阶段递归的写法已被移除。链式推进统一由
  // runChainFrom(startKey) 循环驱动，否则「继续执行」与 runner 内部递归
  // 会互相叠加，导致同一阶段被执行两遍。
  return {
    asset_extract: wrap('资产提取', runAssetExtract),
    asset_images: wrap('资产图片', runAssetImages),
    divide: wrap('分镜提取', runDivide),
    keyframes: wrap('帧图生成', runKeyframes),
    videos: wrap('视频生成', runVideos),
    render: wrap('章节渲染', runRender),
  }
}

/** Ordered list of stage keys, used by the chain runner to drive sequential execution. */
export const STAGE_ORDER: StageKey[] = [
  'asset_extract',
  'asset_images',
  'divide',
  'keyframes',
  'videos',
  'render',
]
