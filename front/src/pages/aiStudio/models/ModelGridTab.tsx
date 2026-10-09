import { useState, useMemo } from 'react'
import type { ReactElement } from 'react'
import { Row, Col, Card, Tag, Space, Button, Empty, Tooltip, Badge, Input } from 'antd'
import {
  StarFilled, StarOutlined, EditOutlined, DeleteOutlined, PlusOutlined,
  CheckCircleOutlined, ExclamationCircleOutlined, SearchOutlined,
  FileTextOutlined, PictureOutlined, VideoCameraOutlined,
  ExpandOutlined, AudioOutlined,
} from '@ant-design/icons'
import { MODEL_CATEGORIES, categoryLabelMap, categoryColorMap } from './constants'
import type { Model, Provider } from './types'

const CATEGORY_ICONS: Record<string, ReactElement> = {
  text: <FileTextOutlined />,
  image: <PictureOutlined />,
  video: <VideoCameraOutlined />,
  super_resolution: <ExpandOutlined />,
  tts: <AudioOutlined />,
}

interface Props {
  models: Model[]
  providers: Provider[]
  getDefaultId: (cat: string) => string | undefined
  getDefaultName: (cat: string) => string | undefined
  onSetDefault: (cat: string, mid: string) => void
  onDeleteModel: (m: Model) => void
  onAddModel: (cat?: string) => void
  onEditModel: (m: Model) => void
  actionLoading?: string | null
}

export default function ModelGridTab({
  models, providers,
  getDefaultId, getDefaultName, onSetDefault, onDeleteModel, onAddModel, onEditModel,
  actionLoading,
}: Props) {
  const [filter, setFilter] = useState<string>('all')
  const [search, setSearch] = useState('')

  const providerName = (pid: string) => providers.find(p => p.id === pid)?.name ?? '未知'
  const categoryCount = (cat: string) => models.filter(m => m.category === cat).length

  const filteredModels = useMemo(() => {
    let result = filter === 'all' ? models : models.filter(m => m.category === filter)
    if (search.trim()) {
      const q = search.toLowerCase()
      result = result.filter(m =>
        m.name.toLowerCase().includes(q) ||
        providerName(m.provider_id).toLowerCase().includes(q)
      )
    }
    return result.sort((a, b) => a.name.localeCompare(b.name))
  }, [models, filter, search, providers])

  const handleCardClick = (catKey: string) => {
    if (categoryCount(catKey) === 0) onAddModel(catKey)
    else setFilter(filter === catKey ? 'all' : catKey)
  }

  const renderModelCard = (m: Model) => {
    const isDefault = getDefaultId(m.category) === m.id
    const busy = actionLoading === m.id
    return (
      <Col xs={24} sm={12} md={8} lg={6} key={m.id}>
        <Card
          size="small"
          hoverable
          style={isDefault ? { borderColor: '#52c41a', borderWidth: 1 } : undefined}
          bodyStyle={{ padding: '12px 16px' }}
        >
          <div className="flex items-center justify-between mb-2">
            {isDefault ? (
              <Tag color="gold" icon={<StarFilled />}>默认</Tag>
            ) : (
              <Tooltip title="设为默认">
                <Button type="text" size="small" icon={<StarOutlined />} loading={busy} onClick={() => onSetDefault(m.category, m.id)} />
              </Tooltip>
            )}
            <Space size={0}>
              <Tooltip title="编辑">
                <Button type="text" size="small" icon={<EditOutlined />} disabled={busy} onClick={() => onEditModel(m)} />
              </Tooltip>
              <Tooltip title="删除">
                <Button type="text" size="small" danger icon={<DeleteOutlined />} disabled={busy} onClick={() => onDeleteModel(m)} />
              </Tooltip>
            </Space>
          </div>
          <div className="font-medium text-gray-800 truncate mb-2" title={m.name}>{m.name}</div>
          <div className="flex items-center gap-2">
            <Tag color={categoryColorMap[m.category]} className="m-0">{categoryLabelMap[m.category]}</Tag>
            <span className="text-xs text-gray-400 truncate">{providerName(m.provider_id)}</span>
          </div>
        </Card>
      </Col>
    )
  }

  const renderAddCard = (cat?: string) => (
    <Col xs={24} sm={12} md={8} lg={6}>
      <Card
        size="small"
        hoverable
        className="border-dashed"
        bodyStyle={{ padding: '12px 16px', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 92 }}
        onClick={() => onAddModel(cat)}
      >
        <div className="text-gray-400 text-center">
          <PlusOutlined style={{ fontSize: 20 }} />
          <div className="text-xs mt-1">添加模型</div>
        </div>
      </Card>
    </Col>
  )

  const displayCategories = filter === 'all'
    ? MODEL_CATEGORIES
    : MODEL_CATEGORIES.filter(c => c.key === filter)

  return (
    <div className="overflow-auto p-4 bg-gray-50 min-h-full">
      <Row gutter={[8, 8]} className="mb-4">
        <Col xs={12} sm={8} md={6} lg={4}>
          <Card
            size="small"
            hoverable
            style={filter === 'all' ? { borderColor: '#1677ff', borderWidth: 2 } : undefined}
            bodyStyle={{ padding: '10px 14px' }}
            onClick={() => setFilter('all')}
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-gray-600">全部</span>
              <Badge count={models.length} style={{ backgroundColor: '#1677ff' }} />
            </div>
          </Card>
        </Col>
        {MODEL_CATEGORIES.map(cat => {
          const hasDefault = !!getDefaultId(cat.key)
          const count = categoryCount(cat.key)
          return (
            <Col xs={12} sm={8} md={6} lg={4} key={cat.key}>
              <Card
                size="small"
                hoverable
                style={filter === cat.key ? { borderColor: '#1677ff', borderWidth: 2 } : undefined}
                bodyStyle={{ padding: '10px 14px' }}
                onClick={() => handleCardClick(cat.key)}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-1.5">
                    <span style={{ fontSize: 14, color: '#8c8c8c' }}>{CATEGORY_ICONS[cat.key]}</span>
                    <Tag color={cat.color} className="m-0">{cat.label}</Tag>
                  </div>
                  <Badge count={count} style={{ backgroundColor: hasDefault ? '#52c41a' : count > 0 ? '#fa8c16' : '#d9d9d9' }} />
                </div>
                <div className="text-xs truncate">
                  {hasDefault ? (
                    <span className="text-green-600 flex items-center gap-1">
                      <CheckCircleOutlined /> {getDefaultName(cat.key)}
                    </span>
                  ) : count > 0 ? (
                    <span className="text-orange-500 flex items-center gap-1">
                      <ExclamationCircleOutlined /> {count} 个 · 未设默认
                    </span>
                  ) : (
                    <span className="text-gray-400">点击添加</span>
                  )}
                </div>
              </Card>
            </Col>
          )
        })}
      </Row>

      <div className="mb-4">
        <Input
          placeholder="搜索模型名或供应商..."
          prefix={<SearchOutlined />}
          allowClear
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ maxWidth: 320 }}
        />
      </div>

      {filteredModels.length === 0 && !search ? (
        <Card>
          <Empty description={filter === 'all' ? '暂无模型' : '该类别暂无模型'}>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => onAddModel(filter !== 'all' ? filter : undefined)}>
              添加模型
            </Button>
          </Empty>
        </Card>
      ) : filteredModels.length === 0 && search ? (
        <Card>
          <Empty description="未找到匹配的模型" />
        </Card>
      ) : (
        <div className="space-y-6">
          {displayCategories.map(cat => {
            const catModels = filteredModels.filter(m => m.category === cat.key)
            if (catModels.length === 0 && filter !== 'all') return null
            return (
              <div key={cat.key}>
                <div className="flex items-center gap-2 mb-3">
                  <span style={{ fontSize: 16, color: '#8c8c8c' }}>{CATEGORY_ICONS[cat.key]}</span>
                  <Tag color={cat.color}>{cat.label}</Tag>
                  <Badge count={catModels.length} style={{ backgroundColor: '#1677ff' }} />
                  <Button type="link" size="small" icon={<PlusOutlined />} onClick={() => onAddModel(cat.key)}>添加</Button>
                </div>
                {catModels.length === 0 ? (
                  <div className="text-center py-3 text-gray-400 text-sm border border-dashed border-gray-200 rounded">
                    该类别暂无模型，点击上方"添加"创建
                  </div>
                ) : (
                  <Row gutter={[12, 12]}>
                    {catModels.map(m => renderModelCard(m))}
                    {renderAddCard(cat.key)}
                  </Row>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
