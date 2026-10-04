// Polling + per-stage state orchestration for the ChapterPipeline feature (P2.4).

import { useCallback, useEffect, useRef, useState } from 'react'
import { FilmService } from '../../../../services/generated'
import type { TaskStatus } from '../../../../services/generated'
import type { Stage, StageKey, StagePatch } from './types'

type PipelineStatusData = {
  stage_asset_extract?: Stage['status']
 stage_divide?: Stage['status']
 stage_asset_images?: Stage['status']
  stage_keyframes?: Stage['status']
  stage_videos?: Stage['status']
  shots_count?: number
  pending_count?: number
  linked_count?: number
  candidates_count?: number
  asset_count?: number
}

export type PollHandle = {
  /** Active task id for the stage, null when no task is being tracked. */
  taskId: string | null
  /** Set the callback invoked on every status tick. */
  setOnTick: (cb: ((progress: number, status: TaskStatus) => void) | null) => void
  /** Cancel the active polling loop. */
  cancel: () => void
}

type PollResult = {
  status: 'succeeded' | 'failed' | 'cancelled' | 'timeout'
  progress: number
}

function isTerminal(s: TaskStatus): boolean {
  return s === 'succeeded' || s === 'failed' || s === 'cancelled'
}

/**
 * Poll a task and surface progress + status to the caller. Mirrors the polling
 * pattern in the existing ChapterPipeline (3s interval, ~100 iterations) but
 * routes every tick through `onTick` so the UI can render a live progress bar.
 */
export function useTaskPolling() {
  const cancelRef = useRef<(() => void) | null>(null)

  const poll = useCallback(
    (
      taskId: string,
      onTick: (progress: number, status: TaskStatus) => void,
    ): Promise<PollResult> => {
      cancelRef.current?.()
      let cancelled = false
      cancelRef.current = () => { cancelled = true }

      return new Promise<PollResult>((resolve) => {
        let iter = 0
        const tick = async () => {
          if (cancelled) return resolve({ status: 'cancelled', progress: 0 })
          iter += 1
          let lastProgress = 0
          try {
            const res = await FilmService.getTaskStatusApiV1FilmTasksTaskIdStatusGet({ taskId })
            const status = res.data?.status
            const progress = Math.max(0, Math.min(100, Math.round(res.data?.progress ?? 0)))
            if (status) {
              lastProgress = progress
              onTick(progress, status)
              if (isTerminal(status)) {
                if (status === 'succeeded') return resolve({ status: 'succeeded', progress })
                return resolve({ status: status === 'cancelled' ? 'cancelled' : 'failed', progress })
              }
            }
          } catch {
            // transient network error — keep polling until timeout
          }
          if (iter >= 100) return resolve({ status: 'timeout', progress: lastProgress })
          setTimeout(tick, 3000)
        }
        void tick()
      })
    },
    [],
  )

  const cancel = useCallback(() => {
    cancelRef.current?.()
    cancelRef.current = null
  }, [])

  useEffect(() => () => cancelRef.current?.(), [])

  return { poll, cancel }
}

/** 批量轮询：一批任务共用同一个定时器，避免串行 await 拖长总耗时 */
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
  cancelledItems: TaskPollEntry[]
}

export function useTaskPollingMany(intervalMs = 3000, maxIters = 100) {
  const timerRef = useRef<number | null>(null)
  const cancelRef = useRef<(() => void) | null>(null)

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const pollMany = useCallback(
    (
      entries: TaskPollEntry[],
      onProgress?: (snapshot: PollManySnapshot) => void,
      shouldAbort?: () => boolean,
    ): Promise<PollManyOutcome> => {
      clearTimer()
      let cancelled = false
      cancelRef.current = () => {
        cancelled = true
        clearTimer()
      }

      const settled = new Map<string, TaskStatus>()
      // 停滞检测：某任务连续 STALL_TICK_LIMIT 轮 progress 无变化且非终态，
      // 判定为疑似卡死（后端孤儿任务 / 上游僵死）。不强制改后端状态，
      // 只在前端把它并入"失败明细"，让「仅重试失败项」可以捡回来。
      const STALL_TICK_LIMIT = 40 // 40 轮 x 3s = 约 2 分钟无进度
      const lastProgress = new Map<string, number>()
      const stallTicks = new Map<string, number>()
      const stalled = new Set<string>()
      const snapshotOf = (): PollManySnapshot => {
        let completed = 0
        let failed = 0
        let cancelledCount = 0
        let pending = 0
        for (const entry of entries) {
          const status = settled.get(entry.taskId)
          if (!status) pending += 1
          else if (status === 'succeeded') completed += 1
          else if (status === 'cancelled') cancelledCount += 1
          else failed += 1
        }
        return { completed, failed, cancelled: cancelledCount, pending }
      }

      return new Promise<PollManyOutcome>((resolve) => {
        let iter = 0
        const done = (aborted: boolean, timedOut: boolean) => {
          cancelRef.current = null
          // 收集所有"非成功且不可继续等待"的项：
          // - 后端明确 failed 的
          // - 停滞检测命中的（疑似孤儿任务）
          // - 整体超时仍未终态的
          // 都要进 failedItems，否则「仅重试失败项」永远捡不到它们（旧 bug）。
          const failedItems = entries.filter((e) => {
            const st = settled.get(e.taskId)
            if (st === 'failed') return true
            if (st === 'succeeded' || st === 'cancelled') return false
            return timedOut || stalled.has(e.taskId)
          })
          const cancelledItems = entries.filter((e) => settled.get(e.taskId) === 'cancelled')
          resolve({ ...snapshotOf(), aborted, timedOut, failedItems, cancelledItems })
        }

        const tick = async () => {
          if (cancelled) return done(true, false)
          if (shouldAbort?.()) return done(true, false)

          iter += 1
          const pendingEntries = entries.filter((e) => !settled.has(e.taskId))
          await Promise.all(
            pendingEntries.map(async (entry) => {
              try {
                const res = await FilmService.getTaskStatusApiV1FilmTasksTaskIdStatusGet({ taskId: entry.taskId })
                const status = res.data?.status as TaskStatus | undefined
                if (status && isTerminal(status)) {
                  settled.set(entry.taskId, status)
                  return
                }
                // 非终态：跟踪进度是否停滞
                const progress = Math.max(0, Math.min(100, Math.round(res.data?.progress ?? 0)))
                if (lastProgress.get(entry.taskId) === progress) {
                  const ticks = (stallTicks.get(entry.taskId) ?? 0) + 1
                  stallTicks.set(entry.taskId, ticks)
                  if (ticks >= STALL_TICK_LIMIT) {
                    stalled.add(entry.taskId)
                    console.warn(`[pollMany] task ${entry.taskId} stalled: no progress for ${ticks} ticks`)
                  }
                } else {
                  lastProgress.set(entry.taskId, progress)
                  stallTicks.set(entry.taskId, 0)
                  stalled.delete(entry.taskId)
                }
              } catch {
                // transient error — retry next tick
              }
            }),
          )

          if (pendingEntries.every((e) => settled.has(e.taskId))) {
            onProgress?.(snapshotOf())
            return done(false, false)
          }
          // 所有未完成任务都已停滞：不再死等 maxIters，提前收尾交给重试
          if (pendingEntries.every((e) => stalled.has(e.taskId))) {
            onProgress?.(snapshotOf())
            return done(false, true)
          }
          if (iter >= maxIters) return done(false, true)
          onProgress?.(snapshotOf())
          timerRef.current = window.setTimeout(tick, intervalMs)
        }

        void tick()
      })
    },
    [clearTimer, intervalMs, maxIters],
  )

  const cancelMany = useCallback(() => {
    cancelRef.current?.()
    cancelRef.current = null
  }, [])

  useEffect(() => () => cancelRef.current?.(), [])

  return { pollMany, cancelMany }
}

export function usePipelineState(initial: Stage[]) {
  const [stages, setStages] = useState<Stage[]>(initial)

  const updateStage = useCallback((key: StageKey, patch: StagePatch) => {
    setStages((prev) => prev.map((s) => (s.key === key ? { ...s, ...patch } : s)))
  }, [])

  const resetStageForRun = useCallback((key: StageKey) => {
    setStages((prev) => prev.map((s) => (
     s.key === key
        ? { ...s, status: 'running', progress: 2, output: null, error: null, agentInfo: null }
       : s
   )))
 }, [])

  const resetAllStages = useCallback(() => {
    setStages((prev) => prev.map((s) => ({
      ...s,
      status: 'not_started' as const,
      progress: 0,
      output: null,
      error: null,
      agentInfo: null,
    })))
  }, [])

 const hydrateFromPipelineStatus = useCallback((data: PipelineStatusData) => {
    setStages((prev) => prev.map((s) => {
      if (s.key === 'asset_extract') {
        const status = (data.stage_asset_extract as Stage['status']) || s.status
        return { ...s, status }
      }
     if (s.key === 'divide') {
       const status = (data.stage_divide as Stage['status']) || s.status
       return { ...s, status }
     }
      if (s.key === 'asset_images') {
        const status = (data.stage_asset_images as Stage['status']) || s.status
        return { ...s, status }
      }
      if (s.key === 'keyframes') {
        const status = (data.stage_keyframes as Stage['status']) || s.status
        return { ...s, status }
      }
      if (s.key === 'videos') {
        const status = (data.stage_videos as Stage['status']) || s.status
        return { ...s, status }
      }
     return s
    }))
  }, [])

  return {
    stages,
    setStages,
    updateStage,
   resetStageForRun,
    resetAllStages,
   hydrateFromPipelineStatus,
  }
}

export async function fetchPipelineStatus(chapterId: string): Promise<PipelineStatusData> {
  try {
    const res = await fetch(`/api/v1/studio/chapters/${chapterId}/pipeline-status`)
    const json = await res.json()
    return (json?.data || {}) as PipelineStatusData
  } catch {
    return {}
  }
}
