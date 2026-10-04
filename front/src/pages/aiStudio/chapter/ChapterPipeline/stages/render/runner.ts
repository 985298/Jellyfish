// 阶段⑥：章节渲染（一键合成成片）
import type { PipelineCtx, ExecResult } from '../shared/ctx'
import type { StageOutput } from '../../types'

export async function runRender(ctx: PipelineCtx): Promise<ExecResult> {
  const { chapterId } = ctx
  if (!chapterId) return { ok: false, error: '缺少章节' }
  ctx.setLoading(true)
  ctx.resetStageForRun('render')
  try {
    const json = await fetch(`/api/v1/film/chapters/${chapterId}/render`, { method: 'POST' })
      .then((r) => r.json())
      .catch(() => ({}))
    if (!json || json.detail) {
      throw new Error(typeof json?.detail === 'string' ? json.detail : '渲染失败')
    }
    const result = json.data ?? json ?? {}
    const shotCount = Number(result?.shots_processed ?? result?.results?.length ?? 0)
    const finalUrl = result?.final_url || undefined
    const output: StageOutput = {
      count: shotCount,
      label: '个镜头已配音',
      url: typeof finalUrl === 'string' ? finalUrl : undefined,
    }
    ctx.updateStage('render', { status: 'done', progress: 100, output })
    return { ok: true, output, taskId: null }
  } catch (e: any) {
    const error = e?.message || '渲染失败'
    ctx.updateStage('render', { status: 'failed', error })
    return { ok: false, error, taskId: null }
  } finally {
    ctx.setLoading(false)
  }
}

