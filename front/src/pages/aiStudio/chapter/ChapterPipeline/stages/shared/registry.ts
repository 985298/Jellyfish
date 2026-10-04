// 共享：runner 注册表 + 链式顺序（聚合入口）
import { message } from 'antd'
import type { PipelineCtx, RunOptions, ExecResult } from './ctx'
import type { StageKey } from '../../types'
import { runAssetExtract } from '../asset-extract/runner'
import { runAssetImages } from '../asset-image/runner'
import { runDivide } from '../divide/runner'
import { runKeyframes } from '../keyframe/runner'
import { runVideos } from '../video/runner'
import { runRender } from '../render/runner'

export type StageRunner = (opts?: RunOptions) => Promise<ExecResult>

/** Build a map of stage-key -> runner. Each runner handles its own message toast. */
export function buildStageRunners(
  ctx: PipelineCtx,
  opts: {
    onLoading?: (content: string) => void
    onSuccess?: (content: string) => void
    onError?: (content: string) => void
  } = {},
): Record<StageKey, StageRunner> {
  const onLoading = (content: string) =>
    opts.onLoading?.(content) ?? message.loading({ content, key: 'pipe', duration: 0 })
  const onSuccess = (content: string) =>
    opts.onSuccess?.(content) ?? message.success({ content, key: 'pipe' })
  const onError = (content: string) =>
    opts.onError?.(content) ?? message.error({ content, key: 'pipe' })

  const wrap = (
    label: string,
    fn: (ctx: PipelineCtx, opts?: RunOptions) => Promise<ExecResult>,
  ): StageRunner => async (runOpts?: RunOptions) => {
    onLoading(`${label}中...`)
    const res = await fn(ctx, runOpts)
    if (res.ok) {
      const o = res.output
      const countText = o
        ? o.total
          ? `${label}完成 ${o.count ?? 0}/${o.total}`
          : `${label}完成 ${o.count ?? 0} ${o.label || ''}`.trim()
        : `${label}完成`
      onSuccess(countText)
    } else {
      onError(res.error || `${label}失败`)
    }
    return res
  }

  // 注意：runner 自带后继阶段递归的写法已被移除。链式推进统一由
  // runChainFrom(startKey) 循环驱动，否则「继续执行」与 runner 内部递归
  // 会互相叠加，导致同一阶段被执行两遍。
  return {
    asset_extract: wrap('资产提取', runAssetExtract),
    asset_images: wrap('资产图片', runAssetImages),
    divide: wrap('分镜提取', runDivide),
    keyframes: wrap('帧图生成', runKeyframes),
    videos: wrap('视频生成', runVideos),
    render: wrap('章节渲染', runRender),
  }
}

/** Ordered list of stage keys, used by the chain runner to drive sequential execution. */
export const STAGE_ORDER: StageKey[] = [
  'asset_extract',
  'asset_images',
  'divide',
  'keyframes',
  'videos',
  'render',
]

