import type { ReactNode } from 'react'
import { Button, Progress, Tag, Tooltip, Modal, Empty, Spin } from 'antd'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  StopOutlined,
} from '@ant-design/icons'
import { useState, useCallback, useEffect } from 'react'
import type { Stage, StageKey } from './types'

const STATUS_META: Record<Stage['status'], { color: string; text: string }> = {
  done: { color: 'green', text: '已完成' },
  running: { color: 'blue', text: '进行中' },
  partial: { color: 'orange', text: '部分完成' },
  not_started: { color: 'default', text: '未开始' },
  blocked: { color: 'red', text: '阻塞' },
  failed: { color: 'red', text: '失败' },
}

// U6：每阶段产出详情加载器（按 stage.key 拉对应实体列表）
type DetailItem = { id: string; name: string; description?: string; thumbnail?: string | null }

async function loadStageDetails(stageKey: StageKey, projectId?: string, chapterId?: string): Promise<{ items: DetailItem[]; label: string }> {
  if (!projectId) return { items: [], label: '' }
  if (stageKey === 'asset_extract' || stageKey === 'asset_images') {
    const { StudioEntitiesService } = await import('../../../../services/generated')
    const [charRes, sceneRes] = await Promise.all([
      StudioEntitiesService.listEntitiesApiV1StudioEntitiesEntityTypeGet({ entityType: 'character', projectId, page: 1, pageSize: 50 }),
      StudioEntitiesService.listEntitiesApiV1StudioEntitiesEntityTypeGet({ entityType: 'scene', projectId, page: 1, pageSize: 50 }),
    ])
    const chars = ((charRes.data?.items ?? []) as Array<{ id: string; name: string; description?: string; thumbnail?: string | null }>).map((c) => ({ id: c.id, name: c.name, description: c.description, thumbnail: c.thumbnail }))
    const scenes = ((sceneRes.data?.items ?? []) as Array<{ id: string; name: string; description?: string; thumbnail?: string | null }>).map((s) => ({ id: s.id, name: s.name, description: s.description, thumbnail: s.thumbnail }))
    return { items: [...chars, ...scenes], label: '资产（角色 + 场景）' }
  }
  if (stageKey === 'divide' || stageKey === 'keyframes' || stageKey === 'videos' || stageKey === 'render') {
    if (!chapterId) return { items: [], label: '' }
    const { StudioShotsService } = await import('../../../../services/generated')
    const res = await StudioShotsService.listShotsApiV1StudioShotsGet({ chapterId, page: 1, pageSize: 50 })
    const items = ((res.data?.items ?? []) as Array<{ id: string; title?: string; script_excerpt?: string; status?: string }>).map((s) => ({
      id: s.id,
      name: `#${s.title || '镜头'} (${s.status || '—'})`,
      description: s.script_excerpt,
    }))
    return { items, label: stageKey === 'divide' ? '分镜' : stageKey === 'keyframes' ? '帧图' : stageKey === 'videos' ? '视频' : '渲染结果' }
  }
  return { items: [], label: '' }
}

export type StageCardProps = {
  stage: Stage
  index: number
  canRun: boolean
  busy: boolean
  externalLink?: ReactNode
  onRun: (key: StageKey) => void
  projectId?: string
  chapterId?: string
  /** 中止当前阶段（阶段正在进行时显示） */
  onStop?: (key: StageKey) => void
  /** 仅重试该阶段的失败项 */
  onRetryFailed?: (key: StageKey) => void
}

export function StageCard({
  stage,
  index,
  canRun,
  busy,
  externalLink,
  onRun,
  projectId,
  chapterId,
  onStop,
  onRetryFailed,
}: StageCardProps) {
  const meta = STATUS_META[stage.status] || STATUS_META.not_started
  const isRunning = stage.status === 'running'
  const isDone = stage.status === 'done'
  const isFailed = stage.status === 'failed'
  const showProgress = isRunning || (stage.progress > 0 && stage.progress < 100 && !isFailed) || isDone
  const output = stage.output
  const outputText = output
    ? output.total
      ? `产出 ${output.count ?? 0}/${output.total} ${output.label || ''}`.trim()
      : `产出 ${output.count ?? 0} ${output.label || ''}`.trim()
    : null
  // 失败明细：既有简短计数标签，也有用于 Tooltip 的清单
  const failedItems = output?.failedItems ?? []
  const failedItemLabels = failedItems.length
    ? failedItems.map((item) => item.label).join('、')
    : ''

  // U6：产出详情抽屉
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailItems, setDetailItems] = useState<DetailItem[]>([])
  const [detailLabel, setDetailLabel] = useState('')
  const openDetail = useCallback(async () => {
    setDetailOpen(true)
    setDetailLoading(true)
    try {
      const { items, label } = await loadStageDetails(stage.key, projectId, chapterId)
      setDetailItems(items)
      setDetailLabel(label)
    } catch {
      setDetailItems([])
    } finally {
      setDetailLoading(false)
    }
  }, [stage.key, projectId, chapterId])
  useEffect(() => {
    if (!detailOpen) {
      setDetailItems([])
      setDetailLabel('')
    }
  }, [detailOpen])

  return (
    <div className="flex items-center justify-between p-3 rounded-lg border border-gray-200">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-3">
          <div className="text-lg">
            {isDone ? (
              <CheckCircleOutlined style={{ color: '#52c41a' }} />
            ) : isFailed ? (
              <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
            ) : isRunning ? (
              <ClockCircleOutlined spin style={{ color: '#1677ff' }} />
            ) : (
              <ClockCircleOutlined style={{ color: '#d9d9d9' }} />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-sm">{index + 1}. {stage.title}</span>
              <Tag color={meta.color}>{meta.text}</Tag>
              {outputText && (
                <a
                  className="text-xs text-blue-500 hover:underline cursor-pointer"
                  onClick={(e) => { e.stopPropagation(); void openDetail() }}
                >
                  {outputText}
                </a>
              )}
              {output?.extra && <span className="text-xs text-orange-500">{output.extra}</span>}
              {output?.url && (
                <a href={output.url} target="_blank" rel="noreferrer" className="text-xs text-blue-500">
                  查看成片
                </a>
              )}
            </div>
            <div className="text-xs text-gray-500 mt-0.5">{stage.desc}</div>
            {stage.error && isFailed && (
              <div className="text-xs text-red-500 mt-0.5 truncate" title={stage.error}>
                {stage.error}
              </div>
            )}
            {showProgress && (
              <Progress
                percent={Math.max(0, Math.min(100, Math.round(stage.progress)))}
                size="small"
                status={isFailed ? 'exception' : isDone ? 'success' : 'active'}
                className="mt-2"
               style={{ maxWidth: 320 }}
             />
           )}
            {stage.agentInfo && (stage.agentInfo.output || stage.agentInfo.toolCalls.length > 0) && (
              <div className="mt-1 p-2 bg-gray-50 rounded text-xs space-y-1">
                {stage.agentInfo.toolCalls.length > 0 && (
                  <div className="flex items-center gap-1 flex-wrap">
                    <span className="text-gray-400">工具:</span>
                    {stage.agentInfo.toolCalls.map((tc, i) => (
                      <Tooltip key={i} title={tc.args ? JSON.stringify(tc.args) : undefined}>
                        <Tag className="m-0" style={{ fontSize: 11 }}>{tc.tool}</Tag>
                      </Tooltip>
                    ))}
                  </div>
                )}
                {stage.agentInfo.output && (
                  <div className="text-gray-500">{stage.agentInfo.output}</div>
                )}
              </div>
            )}
         </div>
        </div>
      </div>
      <div className="flex items-center gap-2 ml-2">
        {externalLink}
        {isRunning && onStop ? (
          <Tooltip title="中止该阶段并取消已提交的任务">
            <Button size="small" danger icon={<StopOutlined />} onClick={() => onStop(stage.key)}>
              中止
            </Button>
          </Tooltip>
        ) : null}
        {failedItems.length > 0 && onRetryFailed && !isRunning ? (
          <Tooltip title={failedItemLabels || undefined}>
            <Button size="small" icon={<ReloadOutlined />} disabled={busy} onClick={() => onRetryFailed(stage.key)}>
              仅重试失败项（{failedItems.length}）
            </Button>
          </Tooltip>
        ) : null}
        {isFailed ? (
          <Button
            size="small"
            icon={<ReloadOutlined />}
            disabled={busy}
            onClick={() => onRun(stage.key)}
          >
            重试
          </Button>
        ) : !isDone && !isRunning ? (
          <Button
            size="small"
            type="primary"
            icon={<PlayCircleOutlined />}
            disabled={busy || !canRun}
            onClick={() => onRun(stage.key)}
          >
            {stage.actionLabel || '执行'}
          </Button>
        ) : null}
      </div>

      <Modal
        title={`${stage.title} · 产出详情`}
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={560}
      >
        {detailLoading ? (
          <div className="flex justify-center py-8"><Spin tip="加载中…" /></div>
        ) : detailItems.length === 0 ? (
          <Empty description={`暂无${detailLabel || '产出'}`} />
        ) : (
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {detailItems.map((item) => (
              <div key={item.id} className="p-2 rounded border border-gray-100 hover:bg-gray-50">
                <div className="font-medium text-sm truncate">{item.name}</div>
                {item.description ? (
                  <div className="text-xs text-gray-500 mt-0.5 line-clamp-2">{item.description}</div>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </Modal>
    </div>
  )
}
