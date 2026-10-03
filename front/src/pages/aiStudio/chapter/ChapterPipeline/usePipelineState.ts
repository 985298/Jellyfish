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
