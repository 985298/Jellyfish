// 阶段 runner：分镜提取
import type { PipelineCtx, ExecResult } from '../shared/ctx'
import { clamp, postForTaskId, pollOne } from '../shared/fanOut'
import type { StageOutput } from '../../types'

export async function runDivide(ctx: PipelineCtx): Promise<ExecResult> {
  const { chapterId, scriptText } = ctx
  if (!chapterId || !scriptText) return { ok: false, error: '缺少章节或剧本文本' }
  ctx.setLoading(true)
  ctx.resetStageForRun('divide')
  try {
    const tid = await postForTaskId('/api/v1/script-processing/divide-async', {
      script_text: scriptText,
      write_to_db: true,
      chapter_id: chapterId,
    })
    if (!tid) throw new Error('No task_id')
    ctx.rememberTaskId?.('divide', tid)
    let progress = 5
    const outcome = await pollOne(ctx, tid, (p) => {
      progress = Math.max(progress, p)
      ctx.updateStage('divide', { progress: clamp(progress), status: 'running' })
    })
    if (outcome !== 'succeeded') throw new Error(outcome === 'timeout' ? '任务超时' : '任务未成功')

    let shotCount = 0
    try {
      const r = await fetch(`/api/v1/studio/shots?chapter_id=${chapterId}`)
      const data = await r.json()
      const items = data?.data?.items || data?.items || []
      shotCount = Array.isArray(items) ? items.length : 0
    } catch {
      shotCount = 0
    }
    const output: StageOutput = { count: shotCount, label: '个镜头' }
    ctx.updateStage('divide', { status: 'done', progress: 100, output })
    return { ok: true, output, taskId: tid }
  } catch (e: any) {
    const error = e?.message || '分镜失败'
    ctx.updateStage('divide', { status: 'failed', error })
    return { ok: false, error, taskId: null }
  } finally {
    ctx.setLoading(false)
  }
}

