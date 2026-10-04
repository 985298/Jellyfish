// 兼容入口：ChapterPipeline.tsx 仍 from './pipelineStages'，实际逻辑已拆到 stages/
export { buildStageRunners, STAGE_ORDER } from './stages/shared/registry'
export type { StageRunner } from './stages/shared/registry'
export type { RunOptions, PipelineCtx, ExecResult, Submission, TaskPollEntry, PollManySnapshot, PollManyOutcome } from './stages/shared/ctx'
export { runFanOutStage, clamp, postForTaskId, pollOne } from './stages/shared/fanOut'
