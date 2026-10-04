// 阶段 runner：资产图片
import type { PipelineCtx, RunOptions, ExecResult } from '../shared/ctx'
import { runFanOutStage } from '../shared/fanOut'

export async function runAssetImages(ctx: PipelineCtx, opts?: RunOptions): Promise<ExecResult> {
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
      const imgId = char.character_images?.[0]?.id
      const body: Record<string, unknown> = {
        prompt: char.description || char.name || '',
      }
      // 只有角色有已绑定图片时才传 image_id，否则后端 400（image_id=1 不存在）
      if (imgId) body.image_id = imgId
      const imgR = await fetch(`/api/v1/studio/image-tasks/characters/${char.id}/image-tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const imgData = await imgR.json()
      return imgData?.data?.task_id ?? null
    },
  })
}

