// Agent orchestration hook: POST + SSE with auto-reconnect.
//
// Replaces the sequential runAll with a single Agent API call that
// streams progress updates via Server-Sent Events. Each SSE event
// carries a stage name + status; the hook maps agent stages to the
// frontend StageKey set and calls updateStage accordingly.
//
// SSE dedup: the backend replays ALL events from index 0 on every
// reconnection, so we track a processedCount and skip events we've
// already seen.

import { useCallback, useEffect, useRef, useState } from 'react'
import type { AgentStageInfo, AgentToolCall, StageKey, StagePatch, StageStatus } from './types'

/** SSE event shape from GET /api/v1/agents/orchestrate/{task_id}/stream. */
type AgentSSEEvent = {
  stage: string
  status: string
  output?: string
  error?: string
  /** Tool calls if the backend includes them (forward-compatible). */
  tools?: Array<{ tool?: string; name?: string; args?: Record<string, unknown>; result?: string }>
  tool_calls?: Array<{ tool?: string; name?: string; args?: Record<string, unknown>; result?: string }>
}

/**
 * Maps Agent orchestrator stage names to frontend StageKeys.
 * build_assets covers both asset_extract and asset_images (the
 * character_designer agent does extraction + image generation together).
 */
const AGENT_STAGE_MAP: Record<string, StageKey[]> = {
  build_assets: ['asset_extract', 'asset_images'],
  extract_shots: ['divide'],
  bind_assets: ['bind_assets'],
  generate_frames: ['keyframes'],
  generate_videos: ['videos'],
}

const ORCHESTRATE_URL = '/api/v1/agents/orchestrate'
const streamUrl = (taskId: string) => `${ORCHESTRATE_URL}/${taskId}/stream`

const MAX_RECONNECT = 10

function mapStatus(status: string): StageStatus {
  if (status === 'completed') return 'done'
  if (status === 'error') return 'failed'
  return 'running'
}

function extractToolCalls(event: AgentSSEEvent): AgentToolCall[] {
  const raw = event.tools || event.tool_calls || []
  return raw.map((t) => ({
    tool: t.tool || t.name || 'unknown',
    args: t.args,
    result: t.result,
  }))
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

export type OrchestrationParams = {
  projectId: string
  chapterId: string
  goal?: string
}

export type OrchestrationCallbacks = {
  updateStage: (key: StageKey, patch: StagePatch) => void
  resetAllStages: () => void
  onComplete: () => void
  onError: (msg: string) => void
}

/**
 * Hook that drives the "一键开始" flow via the Agent SSE API.
 *
 * Returns:
 *   orchestrate  — async function to kick off orchestration
 *   isOrchestrating — boolean for busy state
 *   cancelOrchestration — aborts an in-flight orchestration
 */
export function useAgentOrchestration(callbacks: OrchestrationCallbacks) {
  const callbacksRef = useRef(callbacks)
  callbacksRef.current = callbacks

  const [isOrchestrating, setIsOrchestrating] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const processedCountRef = useRef(0)

  const orchestrate = useCallback(async (params: OrchestrationParams) => {
    const cb = callbacksRef.current

    // Abort any previous orchestration.
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    processedCountRef.current = 0

    cb.resetAllStages()
    setIsOrchestrating(true)

    // 1. POST to create the orchestration task.
    let taskId: string
    try {
      const res = await fetch(ORCHESTRATE_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: params.projectId,
          chapter_id: params.chapterId,
          goal: params.goal || '制作短剧',
        }),
        signal: controller.signal,
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      taskId = json?.data?.task_id ?? json?.task_id
      if (!taskId) throw new Error('未获取到 task_id')
    } catch (e: unknown) {
      if (controller.signal.aborted) return
      cb.onError(e instanceof Error ? e.message : '启动编排失败')
      setIsOrchestrating(false)
      return
    }

    // 2. Connect to SSE stream with auto-reconnect.
    let receivedDone = false
    let hasError = false
    let reconnectAttempts = 0

    while (!receivedDone && !controller.signal.aborted) {
      let hadError = false
      try {
        const res = await fetch(streamUrl(taskId), {
          headers: { Accept: 'text/event-stream' },
          signal: controller.signal,
        })
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let eventIndex = 0

        while (!receivedDone && !controller.signal.aborted) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })

          // SSE events are separated by blank lines (\n\n).
          const parts = buffer.split('\n\n')
          buffer = parts.pop() || ''

          for (const part of parts) {
            if (!part.trim()) continue
            eventIndex++
            // Dedup: server replays all events from index 0 on reconnect.
            if (eventIndex <= processedCountRef.current) continue
            processedCountRef.current = eventIndex

            // Extract the data: payload from the SSE event block.
            const dataStr = part
              .split('\n')
              .filter((l) => l.startsWith('data:'))
              .map((l) => l.slice(5).trim())
              .join('\n')
            if (!dataStr) continue

            let event: AgentSSEEvent
            try {
              event = JSON.parse(dataStr) as AgentSSEEvent
            } catch {
              continue
            }

            // Handle the "done" sentinel — signals overall completion.
            if (event.stage === 'done') {
              receivedDone = true
              break
            }

            // Map agent stage to frontend stage(s).
            const frontendKeys = AGENT_STAGE_MAP[event.stage]
            if (!frontendKeys) continue

            const mappedStatus = mapStatus(event.status)
            const agentInfo: AgentStageInfo = {
              output: event.output,
              toolCalls: extractToolCalls(event),
              error: event.error || null,
            }

            for (const key of frontendKeys) {
              cb.updateStage(key, {
                status: mappedStatus,
                progress: mappedStatus === 'done' ? 100 : mappedStatus === 'running' ? 50 : 0,
                agentInfo,
              })
            }

            if (mappedStatus === 'failed') {
              hasError = true
            }
          }
        }
        // Stream ended normally — reset backoff counter.
        reconnectAttempts = 0
      } catch {
        if (controller.signal.aborted) break
        hadError = true
      }

      if (receivedDone || controller.signal.aborted) break

      // Backoff before reconnecting.
      if (hadError) {
        reconnectAttempts++
        if (reconnectAttempts > MAX_RECONNECT) {
          cb.onError('SSE 连接断开，已达到最大重连次数')
          break
        }
        await sleep(Math.min(1000 * reconnectAttempts, 5000))
      } else {
        // Normal stream end without "done" — brief pause before retry.
        await sleep(1000)
      }
    }

    setIsOrchestrating(false)

    if (controller.signal.aborted) return

    if (hasError) {
      cb.onError('编排过程中有阶段失败')
    } else if (receivedDone) {
      // The render stage is not covered by the Agent orchestrator;
      // mark it done when the orchestration completes successfully.
      cb.updateStage('render', { status: 'done', progress: 100 })
      cb.onComplete()
    }
  }, [])

  const cancelOrchestration = useCallback(() => {
    abortRef.current?.abort()
    setIsOrchestrating(false)
  }, [])

  // Abort on unmount.
  useEffect(() => () => abortRef.current?.abort(), [])

  return { orchestrate, isOrchestrating, cancelOrchestration }
}
