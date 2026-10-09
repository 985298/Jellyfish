import { Row, Col, Card, Tag, Button, Badge, Tooltip, Empty } from 'antd'
import { ThunderboltOutlined, EditOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { PROVIDER_STATUS_MAP } from './constants'
import ProbeResultList from './ProbeResultList'
import type { Provider, Model, ProbeModel } from './types'

interface Props {
  providers: Provider[]
  models: Model[]
  probing: string | null
  probeResults: Record<string, ProbeModel[]>
  selectedModels: Record<string, string[]>
  modelCategories: Record<string, string>
  onAddProvider: () => void
  onEditProvider: (p: Provider) => void
  onDeleteProvider: (p: Provider) => void
  onProbe: (pid: string) => void
  onToggleModel: (pid: string, mid: string) => void
  onCategoryChange: (mid: string, cat: string) => void
  onImport: (pid: string) => void
  onImportAll: (pid: string) => void
}

// 纯展示组件 — 所有 API 调用和状态管理在 ModelManagement
export default function ProvidersTab({
  providers, models, probing, probeResults, selectedModels, modelCategories,
  onAddProvider, onEditProvider, onDeleteProvider, onProbe, onToggleModel, onImport, onImportAll,
  onCategoryChange,
}: Props) {
  const providerModels = (pid: string) => models.filter(m => m.provider_id === pid)

  if (providers.length === 0) {
    return (
      <div className="p-4">
        <Card>
          <Empty description="暂无供应商">
            <Button type="primary" icon={<PlusOutlined />} onClick={onAddProvider}>添加供应商</Button>
          </Empty>
        </Card>
      </div>
    )
  }

  return (
    <div className="overflow-auto p-4 bg-gray-50 min-h-full">
      <div className="mb-4 flex justify-end">
        <Button type="primary" icon={<PlusOutlined />} onClick={onAddProvider}>添加供应商</Button>
      </div>
      <Row gutter={[12, 12]}>
        {providers.map(p => {
          const pModels = providerModels(p.id)
          return (
            <Col xs={24} md={12} lg={8} key={p.id}>
              <Card size="small" className="h-full" bodyStyle={{ padding: '12px 16px' }}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-800">{p.name}</span>
                    <Tag color={PROVIDER_STATUS_MAP[p.status]?.color}>{PROVIDER_STATUS_MAP[p.status]?.text}</Tag>
                  </div>
                  <Badge count={pModels.length} style={{ backgroundColor: '#1677ff' }} />
                </div>
                <div className="text-xs text-gray-400 truncate mb-3" title={p.base_url}>{p.base_url}</div>
                <div className="flex items-center gap-2 mb-2">
                  <Button type="primary" size="small" icon={<ThunderboltOutlined />} loading={probing === p.id} onClick={() => onProbe(p.id)}>
                    获取模型
                  </Button>
                  <Tooltip title="编辑"><Button type="text" size="small" icon={<EditOutlined />} onClick={() => onEditProvider(p)} /></Tooltip>
                  <Tooltip title="删除"><Button type="text" size="small" danger icon={<DeleteOutlined />} onClick={() => onDeleteProvider(p)} /></Tooltip>
                </div>
                {pModels.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-2">
                    {pModels.map(m => (<Tag key={m.id} className="m-0">{m.name}</Tag>))}
                  </div>
                )}
                {probeResults[p.id]?.length > 0 && (
                  <ProbeResultList
                    models={probeResults[p.id]}
                    existingModels={pModels}
                    selected={selectedModels[p.id] ?? []}
                    categories={modelCategories}
                    onToggle={(mid) => onToggleModel(p.id, mid)}
                    onCategoryChange={(mid, cat) => onCategoryChange(mid, cat)}
                    onImport={() => onImport(p.id)}
                    onImportAll={() => onImportAll(p.id)}
                  />
                )}
                {probeResults[p.id]?.length === 0 && (
                  <div className="mt-2 text-center text-gray-400 text-xs border-t border-gray-100 pt-2">未发现可用模型，可手动添加</div>
                )}
              </Card>
            </Col>
          )
        })}
      </Row>
    </div>
  )
}
