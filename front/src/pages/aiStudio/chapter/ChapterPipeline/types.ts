// Shared types for the ChapterPipeline feature (P2.4 enhancement).

export type StageStatus =
  | 'not_started'
  | 'running'
  | 'done'
  | 'failed'
  | 'blocked'
  | 'partial'

export type StageKey =
 | 'asset_extract'
 | 'asset_images'
 | 'divide'
 | 'keyframes'
 | 'videos'
 | 'render'

export type StageOutput = {
  /** 产出数量（已完成） */
  count?: number
  /** 总数（用于 x/y 展示） */
  total?: number
  /** 单位标签，如 "图片"/"镜头" */
  label?: string
  /** 附加说明，如 "失败 2" */
  extra?: string
  /** 失败明细，用于「仅重试失败项」 */
  failedItems?: StageOutputFailedItem[]
  /** 成片访问地址（render 阶段） */
  url?: string
}

/** 单个失败项，id 用于重跑时作为目标子集下发 */
export type StageOutputFailedItem = {
  id: string
  label: string
}

export type Stage = {
  key: StageKey
  title: string
  desc: string
  status: StageStatus
  /** 0-100 进度百分比 */
  progress: number
  output?: StageOutput | null
 actionLabel?: string
 retryLabel?: string
 error?: string | null
  agentInfo?: AgentStageInfo | null
}

export type StagePatch = Partial<Omit<Stage, 'key' | 'title' | 'desc'>>

export type ExecResult = { ok: boolean; output?: StageOutput; error?: string; taskId?: string | null }

/** A single tool invocation recorded by the Agent during a stage. */
export type AgentToolCall = {
  tool: string
  args?: Record<string, unknown>
  result?: string
}

/** Agent thinking metadata attached to a stage card. */
export type AgentStageInfo = {
  /** Human-readable output from the agent (e.g. "提取了5个角色"). */
  output?: string
  /** Tools called during this stage. */
  toolCalls: AgentToolCall[]
  /** Error message if the stage failed. */
  error?: string | null
}
