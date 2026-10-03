import { useEffect, useMemo, useState } from 'react'
import { Card, Input, Row, Col, Tag, Button, message, Modal, Space, Pagination, Tooltip, Progress } from 'antd'
import { EditOutlined, DeleteOutlined, PlusOutlined, ReloadOutlined, ThunderboltOutlined, StopOutlined } from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import { resolveAssetUrl } from '../utils'
import { DisplayImageCard } from '../components/DisplayImageCard'
import {
  StudioAssetTypeFormModal,
  normalizeStudioAsset,
  type StudioAssetLike,
} from '../components/StudioAssetTypeFormModal'
import { useBatchAssetImageGeneration } from '../hooks/useBatchAssetImageGeneration'

export type { StudioAssetLike }

function normalizeAsset(asset: StudioAssetLike): StudioAssetLike {
  return normalizeStudioAsset(asset)
}

type AssetMutationPayload = Record<string, unknown> & {
  name: string
  description?: string
  tags?: string[]
  view_count?: number | null
  thumbnail?: string
}

type AssetCreatePayload = Record<string, unknown> & {
  name: string
  thumbnail?: string
}

export function AssetTypeTab({
  label,
  tabKey,
  listAssets,
  createAsset,
  updateAsset,
  deleteAsset,
  onEditAsset,
  projectId,
}: {
  label: string
  tabKey: 'scene' | 'prop' | 'costume'
  listAssets: (params: { q?: string; projectId?: string | null; page: number; pageSize: number }) => Promise<{ items: StudioAssetLike[]; total: number }>
  createAsset: (payload: AssetCreatePayload) => Promise<StudioAssetLike>
  updateAsset: (id: string, payload: AssetMutationPayload) => Promise<StudioAssetLike>
  deleteAsset: (id: string) => Promise<void>
  onEditAsset?: (asset: StudioAssetLike) => void
  projectId?: string
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [assets, setAssets] = useState<StudioAssetLike[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(12)
  const [total, setTotal] = useState(0)

  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<StudioAssetLike | null>(null)
  const [createSeed, setCreateSeed] = useState<{
    name: string
    desc: string
    visualStyle?: '现实' | '动漫'
    style?: string
  } | null>(null)
  const [fromShotCreateContext, setFromShotCreateContext] = useState<{
    projectId: string
    chapterId: string
    shotId: string
  } | null>(null)

  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewUrl, setPreviewUrl] = useState('')
  const [previewTitle, setPreviewTitle] = useState('')

  const filtered = useMemo(() => {
    const arr = Array.isArray(assets) ? assets : []
    // 选中项目时 assets 已是该项目全部资产（客户端过滤），需做客户端分页切片，
    // 与底部 Pagination 联动；未选项目时 assets 为服务端当前页数据，直接展示。
    if (projectId) {
      const start = (page - 1) * pageSize
      return arr.slice(start, start + pageSize)
    }
    return arr
  }, [assets, projectId, page, pageSize])

  const batch = useBatchAssetImageGeneration(tabKey)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  const toggleSelect = (id: string, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })
  }

  const toggleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedIds(new Set(filtered.map((a) => a.id)))
    } else {
      setSelectedIds(new Set())
    }
  }

  const handleBatchGenerate = async () => {
    if (selectedIds.size === 0) {
      message.warning('请先勾选要生成图片的资产')
      return
    }
    const targets = filtered.filter((a) => selectedIds.has(a.id))
    await batch.generate(targets)
    await load()
  }

  const load = async (opts?: { page?: number; pageSize?: number; q?: string }) => {
    setLoading(true)
    try {
      const nextPage = opts?.page ?? page
      const nextPageSize = opts?.pageSize ?? pageSize
      const nextQ = typeof opts?.q === 'string' ? opts.q : search.trim() || undefined
      if (projectId) {
        // 项目模式：后端现已支持 project_id 过滤，但仍按更新时间倒序拉取全量后做客户端分页，
        // 以保持与原有的"项目内全部资产"展示一致。
        const all: StudioAssetLike[] = []
        let p = 1
        const fetchSize = 100
        for (let guard = 0; guard < 200; guard++) {
          const res = await listAssets({ q: nextQ, projectId, page: p, pageSize: fetchSize })
          const items = Array.isArray(res.items) ? res.items.map(normalizeAsset) : []
          all.push(...items)
          if (items.length === 0 || all.length >= (res.total ?? 0)) break
          p += 1
        }
        setAssets(all)
        setTotal(all.length)
      } else {
        const res = await listAssets({ q: nextQ, page: nextPage, pageSize: nextPageSize })
        const items = Array.isArray(res.items) ? res.items.map(normalizeAsset) : []
        setAssets(items)
        setTotal(res.total)
      }
    } catch {
      message.error('加载资产失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    // 项目模式：分页是客户端切片，仅 projectId 变化时重新拉取全量；
    // 非项目模式：page/pageSize 变化时拉取对应服务端页。
    if (projectId) return
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize])

  useEffect(() => {
    // projectId 变化（含进入/退出项目模式）时重新拉取。
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const openCreate = () => {
    setEditing(null)
    setCreateSeed(null)
    setFromShotCreateContext(null)
    setEditOpen(true)
  }

  useEffect(() => {
    const create = searchParams.get('create')
    const name = searchParams.get('name') ?? ''
    const desc = searchParams.get('desc') ?? ''
    const tab = searchParams.get('tab')
    const projectId = searchParams.get('projectId')?.trim() ?? ''
    const chapterId = searchParams.get('chapterId')?.trim() ?? ''
    const shotId = searchParams.get('shotId')?.trim() ?? ''
    const visualStyle = (searchParams.get('visualStyle')?.trim() || '') as '现实' | '动漫' | ''
    const style = searchParams.get('style')?.trim() ?? ''
    if (create === '1' && tab === tabKey) {
      setEditing(null)
      setCreateSeed({
        name,
        desc,
        visualStyle: visualStyle || undefined,
        style: style || undefined,
      })
      if (projectId && chapterId && shotId) {
        setFromShotCreateContext({ projectId, chapterId, shotId })
      } else {
        setFromShotCreateContext(null)
      }
      setEditOpen(true)
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          next.delete('create')
          next.delete('name')
          next.delete('desc')
          next.delete('projectId')
          next.delete('chapterId')
          next.delete('shotId')
          next.delete('visualStyle')
          next.delete('style')
          return next
        },
        { replace: true },
      )
    }
  }, [searchParams, setSearchParams, tabKey])

  const openEdit = (asset: StudioAssetLike) => {
    setEditing(asset)
    setCreateSeed(null)
    setFromShotCreateContext(null)
    setEditOpen(true)
  }

  const handleEdit = (asset: StudioAssetLike) => {
    if (onEditAsset) {
      onEditAsset(asset)
      return
    }
    openEdit(asset)
  }

  const handleModalCancel = () => {
    setEditOpen(false)
    setEditing(null)
    setCreateSeed(null)
    setFromShotCreateContext(null)
  }

  const handleDelete = (asset: StudioAssetLike) => {
    Modal.confirm({
      title: `删除${label}资产？`,
      content: `将删除「${asset.name}」。`,
      okText: '删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deleteAsset(asset.id)
          message.success('已删除')
          await load()
        } catch {
          message.error('删除失败')
        }
      },
    })
  }

  const openPreview = (asset: StudioAssetLike) => {
    const thumbnailUrl = resolveAssetUrl(asset.thumbnail)
    if (!thumbnailUrl) {
      message.info('未生成图片')
      return
    }
    setPreviewTitle(asset.name)
    setPreviewUrl(thumbnailUrl)
    setPreviewOpen(true)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Input.Search
          placeholder={`搜索${label}名称、描述或标签`}
          allowClear
          className="max-w-sm"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onSearch={() => {
            setPage(1)
            void load()
          }}
        />
        <Space>
          <Tooltip title="勾选下方资产后批量生成图片">
            <Button
              icon={<ThunderboltOutlined />}
              loading={batch.loading}
              disabled={selectedIds.size === 0}
              onClick={() => void handleBatchGenerate()}
            >
              批量生成图片{selectedIds.size > 0 ? `（${selectedIds.size}）` : ''}
            </Button>
          </Tooltip>
          <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            {`新建${label}`}
          </Button>
        </Space>
      </div>

      {filtered.length > 0 ? (
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <input
            type="checkbox"
            checked={filtered.length > 0 && filtered.every((a) => selectedIds.has(a.id))}
            onChange={(e) => toggleSelectAll(e.target.checked)}
            className="align-middle"
          />
          <span>全选本页（已选 {selectedIds.size} 项）</span>
        </div>
      ) : null}

      <Card loading={loading}>
        <Row gutter={[16, 16]}>
          {filtered.length === 0 ? (
            <Col span={24}>
              <div className="text-center text-gray-500 py-8">{search ? '无匹配资产' : '暂无该类资产'}</div>
            </Col>
          ) : (
            filtered.map((a) => {
              const thumbnailUrl = resolveAssetUrl(a.thumbnail)
              const gs = batch.genStates[a.id]
              return (
                <Col xs={24} sm={12} md={8} lg={6} key={a.id}>
                  <DisplayImageCard
                    title={
                      <div className="flex items-center gap-2 min-w-0">
                        <input
                          type="checkbox"
                          checked={selectedIds.has(a.id)}
                          onChange={(e) => toggleSelect(a.id, e.target.checked)}
                          className="align-middle shrink-0"
                          onClick={(e) => e.stopPropagation()}
                        />
                        <span className="truncate">{a.name}</span>
                      </div>
                    }
                    imageUrl={thumbnailUrl}
                    imageAlt={a.name}
                    placeholder="未生成"
                    onImageClick={() => openPreview(a)}
                    extra={
                      <Space size="small">
                        <Button size="small" type="link" icon={<EditOutlined />} onClick={() => handleEdit(a)}>
                          编辑
                        </Button>
                      </Space>
                    }
                    actions={[
                      <Button
                        type="text"
                        key="del"
                        danger
                        icon={<DeleteOutlined />}
                        size="small"
                        onClick={() => handleDelete(a)}
                      />,
                    ]}
                    meta={
                      <>
                        <div className="text-xs text-gray-500 mb-2 line-clamp-2">{a.description || '暂无描述'}</div>
                        <div className="flex flex-wrap gap-1">
                          {typeof a.view_count === 'number' && <Tag color="blue">镜头 {a.view_count}</Tag>}
                          {(a.tags ?? []).slice(0, 3).map((t) => (
                            <Tag key={t}>{t}</Tag>
                          ))}
                        </div>
                        {gs?.taskId && (gs.status === 'pending' || gs.status === 'running') && (
                          <Button size="small" danger icon={<StopOutlined />} loading={gs.status === 'running'} onClick={() => void batch.cancel(a.id)} className="mt-2">
                            取消
                          </Button>
                        )}
                      </>
                    }
                    footer={
                      (() => {
                        if (!gs?.taskId) return null
                        if (gs.status === 'pending' || gs.status === 'running') return <div className="mt-2"><Progress percent={gs.progress} size="small" /></div>
                        if (gs.status === 'succeeded') return <div className="mt-2 text-xs text-green-600">生成成功</div>
                        if (gs.status === 'cancelled') return <div className="mt-2 text-xs text-orange-600">已取消</div>
                        if (gs.status === 'failed') return <div className="mt-2 text-xs text-red-600">生成失败</div>
                        return null
                      })()
                    }
                  />
                </Col>
              )
            })
          )}
        </Row>

        <div className="flex justify-end pt-4">
          <Pagination
            current={page}
            pageSize={pageSize}
            total={total}
            showSizeChanger={false}
            showTotal={(t) => `共 ${t} 条`}
            onChange={(p, ps) => {
              setPage(p)
              setPageSize(ps)
            }}
          />
        </div>
      </Card>

      <StudioAssetTypeFormModal
        open={editOpen}
        label={label}
        entityType={tabKey}
        editing={editing}
        linkProjectId={fromShotCreateContext?.projectId ?? projectId}
        linkChapterId={fromShotCreateContext?.chapterId}
        linkShotId={fromShotCreateContext?.shotId}
        createAsset={createAsset}
        updateAsset={updateAsset}
        onCancel={handleModalCancel}
        seedCreateForm={
          createSeed
            ? {
                name: createSeed.name,
                description: createSeed.desc,
                visual_style: createSeed.visualStyle,
                style: createSeed.style,
              }
            : null
        }
        onSeedConsumed={() => setCreateSeed(null)}
        onSaved={async (ctx) => {
          if (ctx.type === 'update') {
            setAssets((prev) => prev.map((a) => (a.id === ctx.id ? ctx.asset : a)))
            await load()
          } else {
            setPage(1)
            await load({ page: 1 })
          }
        }}
      />

      <Modal
        title={previewTitle}
        open={previewOpen}
        onCancel={() => setPreviewOpen(false)}
        footer={null}
        width={880}
      >
        <div className="w-full flex justify-center bg-gray-50 rounded-md overflow-hidden">
          <img src={previewUrl} alt={previewTitle} className="max-h-[70vh] object-contain" />
        </div>
      </Modal>
    </div>
  )
}
