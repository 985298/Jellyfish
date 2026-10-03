import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Card, Empty, Layout, Segmented, Select, Space, Table, Tag, Tooltip, Typography, message } from 'antd'
import type { TableColumnsType } from 'antd'
import {
  ArrowLeftOutlined,
  EditOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import type { ShotRead, ShotStatus } from '../../../../../services/generated'
import { StudioShotsService, StudioEntitiesService, StudioChaptersService } from '../../../../../services/generated'
import { getChapterShotEditPath } from '../routes'

const { Header, Content } = Layout

type ShotListFilter = 'all' | 'pending' | 'ready' | 'partial'

type ChapterOption = { label: string; value: string }
type SceneOption = { label: string; value: string }
type CharacterOption = { label: string; value: string }

function statusTag(status?: ShotStatus) {
  if (!status) return <span className="text-gray-400">—</span>
  const color = status === 'ready' ? 'success' : 'default'
  return <Tag color={color}>{status}</Tag>
}

export function AllShotsTab() {
  const navigate = useNavigate()
  const { projectId } = useParams<{ projectId: string }>()
  const [loading, setLoading] = useState(false)
  const [shots, setShots] = useState<ShotRead[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [searchText] = useState('')
  const [listFilter, setListFilter] = useState<ShotListFilter>('all')
  const [chapterFilter, setChapterFilter] = useState<string | undefined>(undefined)
  const [sceneFilter, setSceneFilter] = useState<string | undefined>(undefined)
  const [characterFilter, setCharacterFilter] = useState<string | undefined>(undefined)
  const [chapters, setChapters] = useState<ChapterOption[]>([])
  const [scenes, setScenes] = useState<SceneOption[]>([])
  const [characters, setCharacters] = useState<CharacterOption[]>([])
  const [chapterTitleMap, setChapterTitleMap] = useState<Record<string, string>>({})

  const refresh = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const res = await StudioShotsService.listShotsApiV1StudioShotsGet({
        projectId,
        q: searchText.trim() || null,
        page,
        pageSize,
      })
      const items = (res.data?.items ?? []) as ShotRead[]
      const serverTotal = res.data?.pagination?.total ?? 0
      // 客户端按状态过滤（服务端无 status 过滤参数）
      const filtered = items.filter((s) => {
        if (listFilter === 'pending') return s.status !== 'ready'
        if (listFilter === 'ready') return s.status === 'ready'
        return true
      })
      setShots(filtered)
      setTotal(serverTotal)
    } catch {
      message.error('加载分镜失败')
      setShots([])
    } finally {
      setLoading(false)
    }
  }, [projectId, searchText, page, pageSize, listFilter])

  const loadFilterOptions = useCallback(async () => {
    if (!projectId) return
    try {
      const [chRes, scRes, ch2Res] = await Promise.all([
        StudioChaptersService.listChaptersApiV1StudioChaptersGet({ projectId, page: 1, pageSize: 100 }),
        StudioEntitiesService.listEntitiesApiV1StudioEntitiesEntityTypeGet({ entityType: 'scene', projectId, page: 1, pageSize: 100 }),
        StudioEntitiesService.listEntitiesApiV1StudioEntitiesEntityTypeGet({ entityType: 'character', projectId, page: 1, pageSize: 100 }),
      ])
      const chItems = (chRes.data?.items ?? []) as Array<{ id: string; title: string; index: number }>
      setChapters(
        chItems
          .map((c) => ({ label: `第${c.index}章 · ${c.title || '未命名'}`, value: c.id }))
          .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN', { numeric: true })),
      )
      const titleMap: Record<string, string> = {}
      chItems.forEach((c) => { titleMap[c.id] = `第${c.index}章` })
      setChapterTitleMap(titleMap)

      const scItems = (scRes.data?.items ?? []) as Array<{ id: string; name: string }>
      setScenes(scItems.map((s) => ({ label: s.name, value: s.id })))

      const charItems = (ch2Res.data?.items ?? []) as Array<{ id: string; name: string }>
      setCharacters(charItems.map((c) => ({ label: c.name, value: c.id })))
    } catch {
      // 选项加载失败不阻塞主流程
    }
  }, [projectId])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    void loadFilterOptions()
  }, [loadFilterOptions])

  const filterCounts = useMemo(() => {
    return {
      all: total,
      pending: 0,
      ready: 0,
    }
  }, [total])

  const columns: TableColumnsType<ShotRead> = useMemo(
    () => [
      {
        title: '章节',
        dataIndex: 'chapter_id',
        key: 'chapter',
        width: 110,
        render: (v: string) => <span className="text-xs text-gray-600">{chapterTitleMap[v] ?? '—'}</span>,
      },
      {
        title: '序号',
        dataIndex: 'index',
        key: 'index',
        width: 72,
        align: 'center',
      },
      {
        title: '标题',
        dataIndex: 'title',
        key: 'title',
        ellipsis: { showTitle: false },
        render: (t: string) => (
          <Tooltip title={t}>
            <span>{t?.trim() || '—'}</span>
          </Tooltip>
        ),
      },
      {
        title: '状态',
        dataIndex: 'status',
        key: 'status',
        width: 110,
        render: (_: unknown, r) => statusTag(r.status),
      },
      {
        title: '剧本摘录',
        dataIndex: 'script_excerpt',
        key: 'script_excerpt',
        ellipsis: { showTitle: false },
        render: (v: string | undefined) => {
          const raw = v?.trim() ?? ''
          return (
            <Tooltip title={raw || undefined} placement="topLeft">
              <span className="block max-w-full overflow-hidden text-ellipsis whitespace-nowrap">
                {raw || '—'}
              </span>
            </Tooltip>
          )
        },
      },
      {
        title: '操作',
        key: 'actions',
        width: 170,
        render: (_: unknown, r) => (
          <Space size={0} wrap>
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() =>
                projectId && r.chapter_id && r.id &&
                navigate(getChapterShotEditPath(projectId, r.chapter_id, r.id))
              }
            >
              编辑
            </Button>
          </Space>
        ),
      },
    ],
    [chapterTitleMap, navigate, projectId],
  )

  if (!projectId) return <Navigate to="/projects" replace />

  return (
    <Layout style={{ height: '100%', minHeight: 0, background: '#eef2f7' }}>
      <Header
        style={{
          padding: '0 16px',
          background: '#fff',
          borderBottom: '1px solid #e2e8f0',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <Link to={`/projects/${projectId}?tab=all_shots`} className="text-gray-600 hover:text-blue-600 flex items-center gap-1">
          <ArrowLeftOutlined /> 项目工作台
        </Link>
        <div className="min-w-0 flex-1">
          <Typography.Text strong className="truncate block">
            全部分镜
          </Typography.Text>
          <Typography.Text type="secondary" className="text-xs">
            跨章节查看本项目的所有镜头，支持按章节/场景/角色筛选
          </Typography.Text>
        </div>
      </Header>

      <Content style={{ padding: 16, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <Card
          style={{ flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
          bodyStyle={{ flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column', padding: 16 }}
          title={
            <div className="flex flex-wrap items-center gap-3">
              <span>分镜</span>
              <Tag color="blue">共 {total} 个</Tag>
            </div>
          }
          extra={
            <Space wrap>
              <Link to={`/projects/${projectId}/chapters`}>
                <Button type="primary" icon={<ThunderboltOutlined />}>章节列表</Button>
              </Link>
              <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void refresh()}>
                刷新
              </Button>
            </Space>
          }
        >
          <div className="flex flex-col gap-3 flex-1 min-h-0">
            <div className="flex flex-wrap items-center gap-2">
              <Select
                showSearch
                allowClear
                placeholder="按章节筛选"
                style={{ minWidth: 200 }}
                value={chapterFilter}
                options={chapters}
                onChange={(v) => setChapterFilter(v)}
              />
              <Select
                showSearch
                allowClear
                placeholder="按场景筛选"
                style={{ minWidth: 180 }}
                value={sceneFilter}
                options={scenes}
                onChange={(v) => setSceneFilter(v)}
              />
              <Select
                showSearch
                allowClear
                placeholder="按角色筛选"
                style={{ minWidth: 180 }}
                value={characterFilter}
                options={characters}
                onChange={(v) => setCharacterFilter(v)}
              />
              <Segmented
                size="small"
                value={listFilter}
                onChange={(v) => setListFilter(v as ShotListFilter)}
                options={[
                  { label: `全部 ${filterCounts.all}`, value: 'all' },
                  { label: '待确认', value: 'pending' },
                  { label: '已就绪', value: 'ready' },
                ]}
              />
            </div>
            <div className="flex-1 min-h-0">
              <Table<ShotRead>
                rowKey="id"
                size="small"
                loading={loading}
                columns={columns}
                dataSource={shots}
                pagination={{
                  current: page,
                  pageSize,
                  showSizeChanger: true,
                  pageSizeOptions: [10, 20, 50, 100],
                  total,
                  onChange: (p, ps) => {
                    setPage(p)
                    setPageSize(ps)
                  },
                }}
                scroll={{ x: 1180, y: 'calc(100vh - 360px)' }}
                locale={{
                  emptyText: !loading && shots.length === 0 ? <Empty description="无匹配分镜" /> : undefined,
                }}
              />
            </div>
          </div>
        </Card>
      </Content>
    </Layout>
  )
}
