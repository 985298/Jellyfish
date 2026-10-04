// 阶段 runner：视频生成
import type { PipelineCtx, RunOptions, ExecResult } from '../shared/ctx'
import { runFanOutStage } from '../shared/fanOut'
import { FilmService } from '../../../../../../services/generated'

export async function runVideos(ctx: PipelineCtx, opts?: RunOptions): Promise<ExecResult> {
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
          // 后端枚举值：first/last/key/first_last/first_last_key/text_only
          // 原前端传 'first_frame' 会 422
          reference_mode: 'first',
          ratio: '9:16',
          prompt: '',
        },
      })
      return vd?.data?.task_id ?? null
    },
  })
}

