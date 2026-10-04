// 共享：fan-out 阶段通用骨架（资产图片/帧图/视频复用）
import type { StageKey, StageOutput, StageOutputFailedItem } from '../../types'
import type { PipelineCtx, RunOptions, Submission, ExecResult, PollManySnapshot, PollManyOutcome } from './ctx'
import { DEFAULT_BATCH_SIZE } from './ctx'

export function clamp(n: number): number {
  return Math.max(0, Math.min(100, Math.round(n)))
}

/** POST to an endpoint and extract data.task_id from the standard envelope. */
export async function postForTaskId(url: string, body: unknown): Promise<string | null> {
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
export async function pollOne(
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
export async function runFanOutStage<T extends { id: string }>(
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

