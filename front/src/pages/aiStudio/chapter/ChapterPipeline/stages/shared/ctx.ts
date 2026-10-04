// 共享：管线上下文类型（每阶段 runner 都依赖这个 ctx 接口）
import type { StageKey, StageOutput, StagePatch } from '../../types'

export type Submission = { id: string; label: string; taskId: string }

export type RunOptions = {
  /** 只跑这些实体（「仅重试失败项」用） */
  onlyIds?: string[]
  /** 每批并发提交的任务数 */
  batchSize?: number
}

/** 默认每批任务数。设为 999 = 一次性提交全部，用后端自己的并发控制排队。
 *  用户可在界面切到 1/3/5/10 做手动分批，但默认行为是全量并发。 */
export const DEFAULT_BATCH_SIZE = 999

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

