import { useEffect, useMemo, useState } from 'react'
import { Button, Card, Checkbox, Empty, Input, Modal, Pagination, Progress, Space, Tag, Tooltip, message } from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined, StopOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { StudioEntitiesApi } from '../../../../services/studioEntities'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { resolveAssetUrl } from '../utils'
import { DisplayImageCard } from '../components/DisplayImageCard'
import { ActorEntityFormModal, type ActorEntityLike } from '../components/ActorEntityFormModal'
import { useBatchAssetImageGeneration } from '../hooks/useBatchAssetImageGeneration'

export function ActorsTab({ projectId: propProjectId }: { projectId?: string } = {}) {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [actors, setActors] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(12)
  const [total, setTotal] = useState(0)

  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<ActorEntityLike | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [fromShotCreateContext, setFromShotCreateContext] = useState<{
    projectId: string
    chapterId: string
    shotId: string
  } | null>(null)
  const urlProjectId = searchParams.get('projectId')?.trim() ?? ''
  // 顶部项目选择器（propProjectId）优先；兼容 URL 中携带的 projectId（shot 内新建场景）
  const projectId = propProjectId ?? urlProjectId
  const createProjectId = fromShotCreateContext?.projectId ?? projectId

  const batch = useBatchAssetImageGeneration('character')

  const load = async (opts?: { page?: number; pageSize?: number; q?: string }) => {
    setLoading(true)
    try {
      const nextPage = opts?.page ?? page
      const nextPageSize = opts?.pageSize ?? pageSize
      const q = typeof opts?.q === 'string' ? opts.q : search.trim() || undefined
      if (projectId) {
        // 项目模式：后端现已支持 project_id 过滤，但仍按更新时间倒序拉取全量后做客户端分页，
        // 以保持与原有的"项目内全部角色"展示一致。
        const all: Record<string, unknown>[] = []
        let p = 1
        const fetchSize = 100
        for (let guard = 0; guard < 200; guard++) {
          const res = await StudioEntitiesApi.list('character', {
            page: p,
            pageSize: fetchSize,
            q: q ?? null,
            projectId,
            order: 'updated_at',
            isDesc: true,
          })
          const items = (res.data?.items ?? []) as Record<string, unknown>[]
          all.push(...items)
          const serverTotal = res.data?.pagination?.total ?? 0
          if (items.length === 0 || all.length >= serverTotal) break
          p += 1
        }
        setActors(all as unknown as typeof actors)
        setTotal(all.length)
      } else {
        const res = await StudioEntitiesApi.list('character', {
          page: nextPage,
          pageSize: nextPageSize,
          q: q ?? null,
          order: 'updated_at',
          isDesc: true,
        })
        const items = res.data?.items ?? []
        setActors(items)
        setTotal(res.data?.pagination.total ?? 0)
      }
    } catch {
      message.error('加载演员失败')
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

  useEffect(() => {
    const create = searchParams.get('create')
    const tab = searchParams.get('tab')
    const pid = searchParams.get('projectId')?.trim() ?? ''
    const chapterId = searchParams.get('chapterId')?.trim() ?? ''
    const shotId = searchParams.get('shotId')?.trim() ?? ''
    if (create === '1' && tab === 'actor') {
      setEditing(null)
      if (pid && chapterId && shotId) {
        setFromShotCreateContext({ projectId: pid, chapterId, shotId })
      } else {
        setFromShotCreateContext(null)
      }
      setEditOpen(true)
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        next.delete('create')
        next.delete('name')
        next.delete('desc')
        next.delete('projectId')
        next.delete('chapterId')
        next.delete('shotId')
        return next
      }, { replace: true })
    }
  }, [searchParams, setSearchParams])

  const filtered = useMemo(() => {
    // 选中项目时 actors 为该项目全部角色（客户端过滤），做客户端分页切片与底部 Pagination 联动；
    // 未选项目时 actors 为服务端当前页数据，直接展示。
    if (projectId) {
      const arr = Array.isArray(actors) ? actors : []
      const start = (page - 1) * pageSize
      return arr.slice(start, start + pageSize)
    }
    return Array.isArray(actors) ? actors : []
  }, [actors, projectId, page, pageSize])

  const toggleSelect = (id: string, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })
  }

  const toggleSelectAll = (checked: boolean) => {
    if (checked) setSelectedIds(new Set(filtered.map((a) => a.id)))
    else setSelectedIds(new Set())
  }

  const handleBatchGenerate = async () => {
    if (selectedIds.size === 0) {
      message.warning('请先勾选要生成图片的角色')
      return
    }
    const targets = filtered.filter((a) => selectedIds.has(a.id))
    await batch.generate(targets)
    void load()
  }

  const openCreate = () => {
    setEditing(null)
    setFromShotCreateContext(null)
    setEditOpen(true)
  }

  const openEdit = (a: ActorEntityLike) => {
    setEditing(a)
    setFromShotCreateContext(null)
    setEditOpen(true)
  }

  const handleModalCancel = () => {
    setEditOpen(false)
    setEditing(null)
    setFromShotCreateContext(null)
  }

  return (
    <Card
      title="演员"
      extra={
        <Space>
          <Input.Search
            placeholder="搜索演员"
            allowClear
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onSearch={(v) => { setPage(1); void load({ q: v, page: 1 }) }}
            style={{ width: 240 }}
          />
          <Tooltip title={selectedIds.size === 0 ? '请先勾选要生成图片的角色' : ''}>
            <Button
              icon={<ThunderboltOutlined />}
              loading={batch.loading}
              disabled={selectedIds.size === 0}
              onClick={() => void handleBatchGenerate()}
            >
              批量生成图片{selectedIds.size > 0 ? `（${selectedIds.size}）` : ''}
            </Button>
          </Tooltip>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            刷新
          </Button>
          <Tooltip title={createProjectId ? '' : '请从项目内新建角色'}>
            <Button type="primary" icon={<PlusOutlined />} disabled={!createProjectId} onClick={openCreate}>
              新建
            </Button>
          </Tooltip>
        </Space>
      }
    >
      {filtered.length === 0 && !loading ? (
        <Empty description="暂无演员" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-sm text-gray-600">
            <Checkbox
              checked={filtered.length > 0 && filtered.every((a) => selectedIds.has(a.id))}
              onChange={(e) => toggleSelectAll(e.target.checked)}
            >
              全选本页（已选 {selectedIds.size} 项）
            </Checkbox>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {filtered.map((a) => (
            <DisplayImageCard
              key={a.id}
              title={
                <div className="flex items-center gap-2 min-w-0">
                  <Checkbox
                    checked={selectedIds.has(a.id)}
                    onChange={(e) => toggleSelect(a.id, e.target.checked)}
                  />
                  <span className="truncate">{a.name}</span>
                </div>
              }
              imageUrl={resolveAssetUrl(a.thumbnail)}
              imageAlt={a.name}
              extra={
                <Space>
                  <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(a)}>
                    编辑
                  </Button>
                  <Button size="small" onClick={() => navigate(`/assets/actors/${a.id}/edit`)}>
                    详情
                  </Button>
                  <Button
                    danger
                    size="small"
                    icon={<DeleteOutlined />}
                    onClick={() => {
                      Modal.confirm({
                        title: `删除演员「${a.name}」？`,
                        okText: '删除',
                        cancelText: '取消',
                        okButtonProps: { danger: true },
                        onOk: async () => {
                          try {
                            await StudioEntitiesApi.remove('character', a.id)
                            message.success('已删除')
                            void load()
                          } catch {
                            message.error('删除失败')
                          }
                        },
                      })
                    }}
                  />
                </Space>
              }
              meta={
                <div>
                  {a.description && <div className="text-xs text-gray-600 line-clamp-2">{a.description}</div>}
                  <div className="mt-2 flex flex-wrap gap-1">
                    {(a.tags ?? []).slice(0, 6).map((t: string) => (
                      <Tag key={t} className="m-0">
                        {t}
                      </Tag>
                    ))}
                  </div>
                  {(() => {
                    const gs = batch.genStates[a.id]
                    if (!gs?.taskId) return null
                    if (gs.status === 'pending' || gs.status === 'running') {
                      return <Button size="small" danger icon={<StopOutlined />} loading={gs.status === 'running'} onClick={() => void batch.cancel(a.id)} className="mt-2">取消</Button>
                    }
                    return null
                  })()}
                </div>
              }
              footer={
                (() => {
                  const gs = batch.genStates[a.id]
                  if (!gs?.taskId) return null
                  if (gs.status === 'pending' || gs.status === 'running') return <div className="mt-2"><Progress percent={gs.progress} size="small" /></div>
                  if (gs.status === 'succeeded') return <div className="mt-2 text-xs text-green-600">生成成功</div>
                  if (gs.status === 'cancelled') return <div className="mt-2 text-xs text-orange-600">已取消</div>
                  if (gs.status === 'failed') return <div className="mt-2 text-xs text-red-600">生成失败</div>
                  return null
                })()
              }
            />
          ))}
          </div>
        </div>
      )}

      <div className="mt-4 flex justify-end">
        <Pagination
          current={page}
          pageSize={pageSize}
          total={total}
          showSizeChanger={false}
          onChange={(p, ps) => {
            setPage(p)
            setPageSize(ps)
          }}
        />
      </div>

      <ActorEntityFormModal
        entityType="character"
        open={editOpen}
        editing={editing}
        linkProjectId={createProjectId}
        linkChapterId={fromShotCreateContext?.chapterId}
        linkShotId={fromShotCreateContext?.shotId}
        onCancel={handleModalCancel}
        onSuccess={async (detail) => {
          const createdItem = detail?.created as { id?: string } | undefined
          if (createdItem && page === 1 && !search.trim()) {
            setActors((prev) => [createdItem, ...prev.filter((it) => it.id !== createdItem.id)])
            setTotal((prev) => prev + 1)
          } else {
            await load({ page: 1 })
          }
          setPage(1)
        }}
      />
    </Card>
  )
}
