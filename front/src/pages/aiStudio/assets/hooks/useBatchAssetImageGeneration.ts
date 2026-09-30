import { useCallback, useRef, useState } from 'react'
import { message } from 'antd'
import { FilmService } from '../../../../services/generated'
import type { TaskStatus } from '../../../../services/generated'
import { assetAdapters } from '../assetAdapters'

type AssetViewAngle = 'FRONT' | 'LEFT' | 'RIGHT' | 'BACK' | 'THREE_QUARTER' | 'TOP' | 'DETAIL'
type BatchAssetLike = { id: string; name: string; thumbnail?: string }
type BatchOutcome = { submitted: number; skipped: number; failed: number; succeeded: number; cancelled: number; total: number }
type AdapterKey = keyof typeof assetAdapters
export type AssetGenState = { taskId: string | null; status: TaskStatus; progress: number; cancelRequested: boolean }

function isTerminal(s: TaskStatus): boolean { return s === 'succeeded' || s === 'failed' || s === 'cancelled' }

async function ensureFrontImageSlot(adapterKey: AdapterKey, assetId: string) {
  const adapter = assetAdapters[adapterKey]
  let images = await adapter.listImages(assetId)
  const hasFront = images.some((img: any) => img?.view_angle === 'FRONT')
  if (!hasFront) {
    const hasAny = images.length > 0
    if (!hasAny) await adapter.createImageSlot(assetId, 'FRONT' as AssetViewAngle)
    images = await adapter.listImages(assetId)
  }
  return images.find((img: any) => img?.view_angle === 'FRONT') ?? images[0] ?? null
}

export function useBatchAssetImageGeneration(adapterKey: AdapterKey) {
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState<BatchOutcome | null>(null)
  const [genStates, setGenStates] = useState<Record<string, AssetGenState>>({})
  const stopFlagsRef = useRef<Record<string, () => void>>({})
  const [taskIdsByAsset, setTaskIdsByAsset] = useState<Record<string, string>>({})

  const clearState = useCallback((assetId: string) => {
    setGenStates(p => { const n = { ...p }; delete n[assetId]; return n })
    setTaskIdsByAsset(p => { const n = { ...p }; delete n[assetId]; return n })
    stopFlagsRef.current[assetId]?.()
    delete stopFlagsRef.current[assetId]
  }, [])

  const runSingle = useCallback(async (asset: BatchAssetLike) => {
    const adapter = assetAdapters[adapterKey]
    try {
      const frontImage = await ensureFrontImageSlot(adapterKey, asset.id)
      if (!frontImage) return { outcome: 'skipped' as const }
      const imageId = (frontImage as { id?: number }).id
      if (!imageId) return { outcome: 'skipped' as const }
      const rendered = await adapter.renderPrompt(asset.id, imageId)
      const taskId = await adapter.createGenerationTask(asset.id, imageId, { prompt: rendered.prompt, images: rendered.images })
      if (!taskId) return { outcome: 'failed' as const }
      const initial: AssetGenState = { taskId, status: 'pending', progress: 0, cancelRequested: false }
      setGenStates(p => ({ ...p, [asset.id]: initial }))
      setTaskIdsByAsset(p => ({ ...p, [asset.id]: taskId }))
      let settled = false
      stopFlagsRef.current[asset.id] = () => { settled = true }
      let lastStatus: TaskStatus = 'pending'
      for (let i = 0; i < 30; i++) {
        if (settled) break
        await new Promise(r => setTimeout(r, 2000))
        try {
          const res = await FilmService.getTaskStatusApiV1FilmTasksTaskIdStatusGet({ taskId })
          const status = res.data?.status
          if (!status) continue
          lastStatus = status
          const next: AssetGenState = { taskId, status, progress: res.data?.progress ?? 0, cancelRequested: res.data?.cancel_requested ?? false }
          setGenStates(p => ({ ...p, [asset.id]: next }))
          if (isTerminal(status)) break
        } catch {}
      }
      return lastStatus === 'succeeded' ? { outcome: 'succeeded' as const } : lastStatus === 'cancelled' ? { outcome: 'cancelled' as const } : { outcome: 'failed' as const }
    } catch { return { outcome: 'failed' as const } }
  }, [adapterKey])

  const generate = useCallback(async (assets: BatchAssetLike[], opts?: { parallel?: number }): Promise<BatchOutcome> => {
    const parallel = opts?.parallel ?? 3
    const total = assets.length
    const outcome: BatchOutcome = { submitted: 0, skipped: 0, failed: 0, succeeded: 0, cancelled: 0, total }
    if (!total) { message.info('未选择资产'); return outcome }
    setLoading(true); setProgress({ ...outcome })
    async function runOne(a: BatchAssetLike) {
      const r = await runSingle(a)
      if (r.outcome === 'succeeded') { outcome.succeeded++; outcome.submitted++ }
      else if (r.outcome === 'cancelled') { outcome.cancelled++; outcome.submitted++ }
      else if (r.outcome === 'skipped') outcome.skipped++
      else outcome.failed++
      setProgress({ ...outcome }); clearState(a.id)
    }
    const workers = Array.from({ length: Math.min(parallel, total) }, async () => { for (const a of assets) await runOne(a) })
    await Promise.all(workers)
    setLoading(false)
    const parts: string[] = [];
    if (outcome.succeeded > 0) parts.push(`成功 ${outcome.succeeded}`)
    if (outcome.cancelled > 0) parts.push(`已取消 ${outcome.cancelled}`)
    if (outcome.failed > 0) parts.push(`失败 ${outcome.failed}`)
    if (outcome.skipped > 0) parts.push(`跳过 ${outcome.skipped}`)
    if (!parts.length) parts.push('完成')
    message.success(parts.join('，'))
    return outcome
  }, [runSingle, clearState])

  const cancel = useCallback(async (assetId: string) => {
    const taskId = taskIdsByAsset[assetId]
    if (!taskId) return
    stopFlagsRef.current[assetId]?.()
    try { await FilmService.cancelTaskApiV1FilmTasksTaskIdCancelPost({ taskId, requestBody: { reason: '用户主动取消' } }) } catch {}
    clearState(assetId)
  }, [taskIdsByAsset, clearState])

  return { generate, cancel, loading, progress, genStates }
}
