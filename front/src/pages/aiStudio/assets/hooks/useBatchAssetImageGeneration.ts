import { useCallback, useState } from 'react'
import { message } from 'antd'
import { assetAdapters } from '../assetAdapters'

type AssetViewAngle = 'FRONT' | 'LEFT' | 'RIGHT' | 'BACK' | 'THREE_QUARTER' | 'TOP' | 'DETAIL'

type BatchAssetLike = { id: string; name: string; thumbnail?: string }

type BatchOutcome = {
  submitted: number
  skipped: number
  failed: number
  total: number
}

type AdapterKey = keyof typeof assetAdapters

async function ensureFrontImageSlot(adapterKey: AdapterKey, assetId: string) {
  const adapter = assetAdapters[adapterKey]
  let images = await adapter.listImages(assetId)
  const hasFront = images.some((img) => (img as { view_angle?: string }).view_angle === 'FRONT')
  if (!hasFront) {
    const hasAny = images.length > 0
    if (!hasAny) {
      await adapter.createImageSlot(assetId, 'FRONT' as AssetViewAngle)
      images = await adapter.listImages(assetId)
    }
  }
  const front =
    images.find((img) => (img as { view_angle?: string }).view_angle === 'FRONT') ??
    images[0]
  return front ?? null
}

export function useBatchAssetImageGeneration(adapterKey: AdapterKey) {
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState<BatchOutcome | null>(null)

  const generate = useCallback(
    async (assets: BatchAssetLike[]): Promise<BatchOutcome> => {
      const adapter = assetAdapters[adapterKey]
      const total = assets.length
      const outcome: BatchOutcome = { submitted: 0, skipped: 0, failed: 0, total }
      if (total === 0) {
        message.info('未选择资产')
        return outcome
      }
      setLoading(true)
      setProgress({ ...outcome })
      for (const asset of assets) {
        try {
          const frontImage = await ensureFrontImageSlot(adapterKey, asset.id)
          if (!frontImage) {
            outcome.skipped += 1
            setProgress({ ...outcome })
            continue
          }
          const imageId = (frontImage as { id?: number }).id
          if (!imageId) {
            outcome.skipped += 1
            setProgress({ ...outcome })
            continue
          }
          const rendered = await adapter.renderPrompt(asset.id, imageId)
          const taskId = await adapter.createGenerationTask(asset.id, imageId, {
            prompt: rendered.prompt,
            images: rendered.images,
          })
          if (taskId) {
            outcome.submitted += 1
          } else {
            outcome.failed += 1
          }
        } catch {
          outcome.failed += 1
        }
        setProgress({ ...outcome })
      }
      setLoading(false)
      const parts: string[] = [`已提交 ${outcome.submitted}/${total}`]
      if (outcome.skipped > 0) parts.push(`跳过 ${outcome.skipped}`)
      if (outcome.failed > 0) parts.push(`失败 ${outcome.failed}`)
      if (outcome.submitted > 0) message.success(parts.join('，'))
      else message.warning(parts.join('，'))
      return outcome
    },
    [adapterKey],
  )

  return { generate, loading, progress }
}
