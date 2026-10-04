// 阶段 runner：资产提取
import type { PipelineCtx, ExecResult } from '../shared/ctx'
import { clamp, postForTaskId, pollOne } from '../shared/fanOut'
import type { StageOutput } from '../../types'

export async function runAssetExtract(ctx: PipelineCtx): Promise<ExecResult> {
  const { projectId, scriptText } = ctx
  if (!projectId || !scriptText) return { ok: false, error: '缺少项目或剧本文本' }
  ctx.setLoading(true)
  ctx.resetStageForRun('asset_extract')
  try {
    const tid = await postForTaskId('/api/v1/script-processing/asset-extract-async', {
      project_id: projectId,
      script_text: scriptText,
    })
    if (!tid) throw new Error('No task_id')
    ctx.rememberTaskId?.('asset_extract', tid)
    let progress = 5
    const outcome = await pollOne(ctx, tid, (p) => {
      progress = Math.max(progress, p)
      ctx.updateStage('asset_extract', { progress: clamp(progress), status: 'running' })
    })
    if (outcome !== 'succeeded') throw new Error(outcome === 'timeout' ? '任务超时' : '任务未成功')

    let charCount = 0
    try {
      const r = await fetch(`/api/v1/studio/entities/character?project_id=${projectId}`)
      const data = await r.json()
      const items = data?.data?.items || data?.items || []
      charCount = Array.isArray(items) ? items.length : 0
    } catch {
      charCount = 0
    }
    const output: StageOutput = { count: charCount, label: '个资产' }
    ctx.updateStage('asset_extract', { status: 'done', progress: 100, output })
    return { ok: true, output, taskId: tid }
  } catch (e: any) {
    const error = e?.message || '提取失败'
    ctx.updateStage('asset_extract', { status: 'failed', error })
    return { ok: false, error, taskId: null }
  } finally {
    ctx.setLoading(false)
  }
}

