import { Card, Button, Statistic, Row, Col, Progress, Space, Spin, Tag, Tooltip, Grid } from 'antd'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  FileSearchOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import type { TabKey } from '../constants'
import { getChapterShotsPath, getChapterStudioPath, getProjectChaptersPath, getProjectEditorPath } from '../routes'
import { useProject, useChapters } from '../hooks/useProjectData'
import { ensureHasShotsBeforeShooting } from '../ensureHasShotsBeforeShooting'
import { getChapterPreparationState } from '../chapterPreparation'
import {
  loadChapterFlowStats,
  loadProjectFlowStatsForChapters,
  type ChapterFlowStats,
  type ProjectFlowStats,
} from '../projectFlowStats'

const { useBreakpoint } = Grid

// 章节甘特图阶段映射（D3：状态映射 + 项目级甘特图）
// 每个阶段对应一种颜色，6 段彩色横条；移动端降级为文字列表
const STAGE_SEGMENTS = [
  { key: 'asset_extract', label: '资产', color: '#6366f1' },
  { key: 'asset_images', label: '图片', color: '#8b5cf6' },
  { key: 'divide', label: '分镜', color: '#a855f7' },
  { key: 'keyframes', label: '帧图', color: '#ec4899' },
  { key: 'videos', label: '视频', color: '#f59e0b' },
  { key: 'render', label: '渲染', color: '#10b981' },
] as const

// 章节状态 → 推进到的阶段编号（0=未开始, 1=资产提取, ..., 6=渲染完成）
function getChapterStageProgress(chapter: { status?: string; assetStage?: string | null; storyboardCount?: number }): number {
  if (chapter.status === 'done') return 6
  if (chapter.status === 'shooting') return 5
  if (!chapter.assetStage || chapter.assetStage === 'not_started') return 0
  if (chapter.assetStage === 'running') return 1
  if (chapter.assetStage === 'failed' || chapter.assetStage === 'blocked') return 1
  // assetStage done/partial + 无分镜 → 2（资产完成，待分镜）
  if (!(chapter.storyboardCount && chapter.storyboardCount > 0)) return 2
  // 有分镜 → 至少推进到 3（分镜完成）；实际帧图/视频进度需更细数据，此处保守返回 3
  return 3
}

export function DashboardTab({ onSelectTab }: { onSelectTab: (tab: TabKey) => void }) {
  const navigate = useNavigate()
  const { projectId } = useParams<{ projectId: string }>()
  const { project, loading: projectLoading } = useProject(projectId)
  const { chapters, loading: chaptersLoading } = useChapters(projectId)
  const [flowStats, setFlowStats] = useState<ProjectFlowStats>({
    totalShots: 0,
    pendingConfirmShots: 0,
    readyShots: 0,
    generatingShots: 0,
  })
  const [chapterFlowStats, setChapterFlowStats] = useState<ChapterFlowStats[]>([])
  const [flowStatsLoading, setFlowStatsLoading] = useState(false)
  const screens = useBreakpoint()
  const isMobile = !screens.md

  const loading = projectLoading || chaptersLoading
  const chaptersByIndex = [...chapters].sort((a, b) => a.index - b.index)
  const incompleteChapters = chaptersByIndex.filter((c) => c.status !== 'done')
  const recommendedChapter =
    chaptersByIndex.find((chapter) => getChapterPreparationState(chapter).key === 'edit_raw') ??
    chaptersByIndex.find((chapter) => getChapterPreparationState(chapter).key === 'extract_shots') ??
    chaptersByIndex.find((chapter) => getChapterPreparationState(chapter).key === 'prepare_shots') ??
    chaptersByIndex.find((chapter) => getChapterPreparationState(chapter).key === 'shoot') ??
    chaptersByIndex[0] ??
    null

  useEffect(() => {
    let cancelled = false
    if (!projectId || !chapters.length) {
      setFlowStats({
        totalShots: 0,
        pendingConfirmShots: 0,
        readyShots: 0,
        generatingShots: 0,
      })
      setChapterFlowStats([])
      return () => {
        cancelled = true
      }
    }

    const run = async () => {
      setFlowStatsLoading(true)
      try {
        const [stats, chapterStats] = await Promise.all([
          loadProjectFlowStatsForChapters(chapters),
          loadChapterFlowStats(chapters),
        ])
        if (!cancelled) setFlowStats(stats)
        if (!cancelled) setChapterFlowStats(chapterStats)
      } catch {
        if (!cancelled) {
          setFlowStats({
            totalShots: 0,
            pendingConfirmShots: 0,
            readyShots: 0,
            generatingShots: 0,
          })
          setChapterFlowStats([])
        }
      } finally {
        if (!cancelled) setFlowStatsLoading(false)
      }
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [chapters, projectId])

  if (loading && !project) {
    return (
      <div className="flex justify-center items-center py-16">
        <Spin size="large" tip="加载中…" />
      </div>
    )
  }
  if (!project) {
    return null
  }

  const incompleteCount = incompleteChapters.length
  const recommendedState = recommendedChapter ? getChapterPreparationState(recommendedChapter) : null
  const chaptersNeedingRawText = chaptersByIndex.filter((chapter) => getChapterPreparationState(chapter).key === 'edit_raw').length
  const chaptersNeedingShotExtract = chaptersByIndex.filter((chapter) => getChapterPreparationState(chapter).key === 'extract_shots').length
  const chaptersNeedingShotPrep = chaptersByIndex.filter((chapter) => getChapterPreparationState(chapter).key === 'prepare_shots').length
  const chaptersReadyForShoot = chaptersByIndex.filter((chapter) => getChapterPreparationState(chapter).key === 'shoot').length
  const topPendingChapter = [...chapterFlowStats].sort((a, b) => b.pendingConfirmShots - a.pendingConfirmShots)[0]
  const topGeneratingChapter = [...chapterFlowStats].sort((a, b) => b.generatingShots - a.generatingShots)[0]
  const topReadyChapter = [...chapterFlowStats].sort((a, b) => b.readyShots - a.readyShots)[0]

  const handleRecommendedAction = () => {
    if (!projectId) return
    if (!recommendedChapter || !recommendedState) {
      onSelectTab('chapters')
      return
    }
    if (recommendedState.key === 'edit_raw') {
      onSelectTab('chapters')
      navigate(`/projects/${projectId}?tab=chapters&edit=${recommendedChapter.id}`, { replace: false })
      return
    }
    if (recommendedState.key === 'extract_shots') {
      navigate(getChapterShotsPath(projectId, recommendedChapter.id))
      return
    }
    if (recommendedState.key === 'prepare_shots') {
      navigate(getChapterStudioPath(projectId, recommendedChapter.id))
      return
    }
    void ensureHasShotsBeforeShooting({
      projectId,
      chapterId: recommendedChapter.id,
      storyboardCount: recommendedChapter.storyboardCount,
      navigate,
    })
  }

  const chapterTodoCards = [
    {
      key: 'edit_raw',
      title: '待补原文',
      count: chaptersNeedingRawText,
      hint: '这些章节还没进入分镜流程',
      icon: <ClockCircleOutlined />,
    },
    {
      key: 'extract_shots',
      title: '待提取分镜',
      count: chaptersNeedingShotExtract,
      hint: '已有原文，可直接进入分镜提取',
      icon: <ClockCircleOutlined />,
    },
    {
      key: 'prepare_shots',
      title: '待准备镜头',
      count: chaptersNeedingShotPrep,
      hint: '已有分镜，建议进入工作室继续处理',
      icon: <ClockCircleOutlined />,
    },
    {
      key: 'shoot',
      title: '可继续拍摄',
      count: chaptersReadyForShoot,
      hint: '这部分章节已具备继续拍摄条件',
      icon: <CheckCircleOutlined />,
    },
  ] as const

  return (
    <div className="space-y-6">
      <Card size="small">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <div className="font-medium">当前推荐动作</div>
            <div className="text-xs text-gray-500">
              {recommendedChapter && recommendedState
                ? `第${recommendedChapter.index}章 · ${recommendedState.hint}`
                : '暂无章节，可先创建第一章'}
            </div>
          </div>
          <Space wrap>
            <Button onClick={() => onSelectTab('chapters')}>进入章节管理</Button>
            <Button onClick={() => projectId && navigate(getProjectEditorPath(projectId))}>进入后期剪辑</Button>
            <Button
              type="primary"
              icon={recommendedState?.primaryIcon ?? <VideoCameraOutlined />}
              onClick={handleRecommendedAction}
            >
              {recommendedChapter && recommendedState ? recommendedState.primaryAction : '创建第一章'}
            </Button>
          </Space>
        </div>
      </Card>

      <Card title="章节进度甘特图" size="small" extra={
        <Space size="small">
          {STAGE_SEGMENTS.map((seg) => (
            <Tag key={seg.key} color={seg.color} style={{ fontSize: 11 }}>{seg.label}</Tag>
          ))}
        </Space>
      }>
        {chapters.length === 0 ? (
          <div className="text-gray-500 py-4 text-center">暂无章节</div>
        ) : isMobile ? (
          // 移动端降级：列表视图
          <div className="space-y-2">
            {chaptersByIndex.slice(0, 10).map((ch) => {
              const stage = getChapterStageProgress(ch)
              return (
                <div key={ch.id} className="flex items-center justify-between gap-2 py-1">
                  <span className="text-sm truncate">第{ch.index}章 · {ch.title || '未命名'}</span>
                  <Tag color={ch.status === 'done' ? 'success' : ch.status === 'partial' ? 'warning' : 'default'}>
                    {stage === 6 ? '已完成' : stage === 0 ? '未开始' : `卡在${STAGE_SEGMENTS[stage - 1]?.label ?? ''}阶段`}
                  </Tag>
                </div>
              )
            })}
          </div>
        ) : (
          // 桌面端：甘特图（每行一章，6 段彩色横条）
          <div className="space-y-1">
            {chaptersByIndex.slice(0, 30).map((ch) => {
              const stage = getChapterStageProgress(ch)
              const isPartial = ch.status === 'partial'
              const onClick = () => projectId && navigate(getChapterStudioPath(projectId, ch.id))
              return (
                <div key={ch.id} className="flex items-center gap-2 py-1 hover:bg-gray-50 rounded cursor-pointer" onClick={onClick}>
                  <div className="w-32 shrink-0 truncate text-xs">
                    第{ch.index}章 · {ch.title || '未命名'}
                  </div>
                  <div className="flex-1 flex gap-0.5">
                    {STAGE_SEGMENTS.map((seg, i) => {
                      const segDone = i < stage
                      const segPartial = isPartial && i === stage - 1
                      return (
                        <Tooltip key={seg.key} title={`${seg.label}：${segDone ? (segPartial ? '部分完成' : '完成') : '未开始'}`}>
                          <div
                            style={{
                              flex: 1,
                              height: 18,
                              borderRadius: 3,
                              background: segDone ? (segPartial ? `${seg.color}88` : seg.color) : '#f3f4f6',
                              border: `1px solid ${segDone ? seg.color : '#e5e7eb'}`,
                            }}
                          />
                        </Tooltip>
                      )
                    })}
                  </div>
                  <div className="w-24 shrink-0 text-right">
                    <Tag color={ch.status === 'done' ? 'success' : ch.status === 'partial' ? 'warning' : 'default'} style={{ fontSize: 11 }}>
                      {stage === 6 ? '完成' : stage === 0 ? '未开始' : `${stage}/6`}
                    </Tag>
                  </div>
                </div>
              )
            })}
            {chaptersByIndex.length > 30 ? (
              <div className="text-center text-xs text-gray-500 pt-2">仅显示前 30 章，共 {chaptersByIndex.length} 章</div>
            ) : null}
          </div>
        )}
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card size="small" className="h-full">
            <Statistic title="未完成章节" value={incompleteCount} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card size="small" className="h-full">
            <Statistic
              title="待确认分镜"
              value={flowStats.pendingConfirmShots}
              suffix={flowStats.totalShots ? `/ ${flowStats.totalShots}` : undefined}
              loading={flowStatsLoading}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card size="small" className="h-full">
            <Statistic
              title="已就绪分镜"
              value={flowStats.readyShots}
              loading={flowStatsLoading}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card size="small" className="h-full">
            <Statistic
              title="生成中分镜"
              value={flowStats.generatingShots}
              loading={flowStatsLoading}
              prefix={<ClockCircleOutlined />}
            />
            <Progress
              percent={flowStats.totalShots ? Math.round((flowStats.readyShots / flowStats.totalShots) * 100) : project.progress}
              showInfo={false}
              size="small"
              strokeColor={{ from: '#6366f1', to: '#a855f7' }}
              className="mt-1"
            />
          </Card>
        </Col>
      </Row>

      <Card
        title="当前待办"
        size="small"
        extra={
          <Button type="link" onClick={() => projectId && navigate(getProjectChaptersPath(projectId))}>
            查看全部
          </Button>
        }
      >
        <div className="flex gap-3 overflow-x-auto pb-2" style={{ minHeight: 140 }}>
          {chapters.length === 0 ? (
            <div className="flex-1 flex items-center justify-center text-gray-500 py-8">
              还没有任何章节，
              <Button type="link" className="p-0" onClick={() => onSelectTab('chapters')}>
                立即创建第一章
              </Button>
            </div>
          ) : (
            chapterTodoCards.map((item) => (
              <Card
                key={item.key}
                size="small"
                hoverable
                className="shrink-0 cursor-pointer"
                style={{ width: 280 }}
                onClick={() => onSelectTab('chapters')}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="font-medium truncate">{item.title}</div>
                  <span className="text-gray-400">{item.icon}</span>
                </div>
                <div className="mt-1 text-2xl font-semibold">{item.count}</div>
                <div className="text-xs text-gray-500 mt-1">
                  {item.hint}
                </div>
              </Card>
            ))
          )}
        </div>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={14}>
          <Card title="动态摘要" size="small">
            <div className="space-y-3 text-sm">
              <div className="rounded-md border border-amber-100 bg-amber-50 px-3 py-2">
                <div className="flex items-center gap-2 font-medium text-amber-800">
                  <ClockCircleOutlined />
                  待确认压力最大
                </div>
                <div className="mt-1 text-gray-700">
                  {topPendingChapter && topPendingChapter.pendingConfirmShots > 0
                    ? `第${topPendingChapter.chapterIndex ?? '-'}章还有 ${topPendingChapter.pendingConfirmShots} 条分镜待确认，建议优先处理。`
                    : '当前没有待确认分镜积压。'}
                </div>
              </div>

              <div className="rounded-md border border-blue-100 bg-blue-50 px-3 py-2">
                <div className="flex items-center gap-2 font-medium text-blue-800">
                  <VideoCameraOutlined />
                  当前生成最活跃
                </div>
                <div className="mt-1 text-gray-700">
                  {topGeneratingChapter && topGeneratingChapter.generatingShots > 0
                    ? `第${topGeneratingChapter.chapterIndex ?? '-'}章有 ${topGeneratingChapter.generatingShots} 条分镜正在生成，可以继续关注结果。`
                    : '当前没有分镜处于生成中。'}
                </div>
              </div>

              <div className="rounded-md border border-emerald-100 bg-emerald-50 px-3 py-2">
                <div className="flex items-center gap-2 font-medium text-emerald-800">
                  <CheckCircleOutlined />
                  最适合继续推进
                </div>
                <div className="mt-1 text-gray-700">
                  {topReadyChapter && topReadyChapter.readyShots > 0
                    ? `第${topReadyChapter.chapterIndex ?? '-'}章已有 ${topReadyChapter.readyShots} 条已就绪分镜，适合继续推进视频生成。`
                    : '当前还没有明显可继续推进的视频生成批次。'}
                </div>
              </div>
            </div>
            <Button
              type="link"
              className="p-0 mt-3"
              icon={<FileSearchOutlined />}
              onClick={() => onSelectTab('chapters')}
            >
              去章节里继续推进
            </Button>
          </Card>
        </Col>
        <Col xs={24} md={10}>
          <Card title="资产健康快照" size="small">
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>角色</span>
                <span className="text-gray-500">{project.stats.roles} 项</span>
              </div>
              <Progress percent={80} size="small" showInfo={false} />
              <div className="flex justify-between text-sm">
                <span>场景</span>
                <span className="text-gray-500">{project.stats.scenes} 项</span>
              </div>
              <Progress percent={60} size="small" showInfo={false} />
              <div className="flex justify-between text-sm">
                <span>道具</span>
                <span className="text-gray-500">{project.stats.props} 项</span>
              </div>
              <Progress percent={75} size="small" showInfo={false} />
            </div>
            <Button type="link" className="p-0 mt-2" onClick={() => navigate(`/assets?projectId=${projectId}`)}>
              管理资产
            </Button>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
