// 阶段 runner：帧图生成
import type { PipelineCtx, RunOptions, ExecResult } from '../shared/ctx'
import { runFanOutStage } from '../shared/fanOut'

export async function runKeyframes(ctx: PipelineCtx, opts?: RunOptions): Promise<ExecResult> {
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
        body: JSON.stringify({
          frame_type: 'first',
          model_id: null,
          // 后端 required 字段：prompt 用镜头剧文兜底，target_ratio 默认竖屏 9:16
          prompt: shot.script_excerpt || shot.title || '',
          target_ratio: '9:16',
        }),
      })
      const fd = await fr.json()
      return fd?.data?.task_id ?? null
    },
  })
}

