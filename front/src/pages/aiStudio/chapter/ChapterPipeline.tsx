import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Button, Card, Progress, Result, Space, Tag, Tooltip, message } from 'antd'
import { ThunderboltOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { StudioChaptersService } from '../../../services/generated'
import { useParams, Link } from 'react-router-dom'
import { StageCard } from './ChapterPipeline/StageCard'
import { usePipelineState, useTaskPolling, fetchPipelineStatus } from './ChapterPipeline/usePipelineState'
import { useAgentOrchestration } from './ChapterPipeline/useAgentOrchestration'
import { buildStageRunners, STAGE_ORDER } from './ChapterPipeline/pipelineStages'
import type { ExecResult, Stage, StageKey } from './ChapterPipeline/types'

// 失败恢复策略：可跳过失败（partial 容错推进）vs 必须暂停（后续阶段无法跑）
const PAUSE_STAGES: ReadonlySet<StageKey> = new Set(['asset_extract', 'asset_images', 'divide'])

const STAGE_LABELS: Record<StageKey, string> = {
  asset_extract: '资产提取',
  asset_images: '资产图片',
  divide: '分镜提取',
  keyframes: '镜头帧图',
  videos: '视频生成',
  render: '章节渲染',
}

const INITIAL_STAGES: Stage[] = [
  {
    key: 'asset_extract',
    title: '资产提取',
    desc: 'LLM 从剧本提取角色/场景/道具/服装',
    status: 'not_started',
    progress: 0,
    actionLabel: '执行',
  },
  {
    key: 'asset_images',
   title: '资产图片',
   desc: '生成角色/场景参考图，锁定外貌',
    status: 'not_started',
    progress: 0,
    actionLabel: '执行',
  },
 {
   key: 'divide',
   title: '分镜提取',
   desc: 'LLM 带资产清单拆分镜头（Agnes三段式）',
   status: 'not_started',
   progress: 0,
   actionLabel: '执行',
 },
 {
   key: 'keyframes',
   title: '镜头帧图',
   desc: 'img2img 引用资产参考图生成关键帧',
    status: 'not_started',
    progress: 0,
    actionLabel: '执行',
  },
  {
    key: 'videos',
   title: '视频生成',
   desc: '关键帧做首帧，first_frame 模式生成竖屏视频',
    status: 'not_started',
    progress: 0,
    actionLabel: '执行',
  },
  {
    key: 'render',
    title: '章节渲染',
    desc: '配音+合成成片',
    status: 'not_started',
    progress: 0,
    actionLabel: '执行',
  },
]

export default function ChapterPipeline() {
  const { projectId, chapterId } = useParams<{ projectId?: string; chapterId?: string }>()
  const [loading, setLoading] = useState(false)
  const [chapterTitle, setChapterTitle] = useState('')
  const [scriptText, setScriptText] = useState('')
  const [runningStage, setRunningStage] = useState<StageKey | null>(null)
  const taskIdRef = useRef<Partial<Record<StageKey, string | null>>>({})
  const chainAbortRef = useRef(false)

  const { stages, updateStage, resetStageForRun, resetAllStages, hydrateFromPipelineStatus } = usePipelineState(INITIAL_STAGES)
  const { poll } = useTaskPolling()
  const [sseReconnectInfo, setSseReconnectInfo] = useState<{ attempt: number; max: number } | null>(null)
  const { orchestrate, isOrchestrating } = useAgentOrchestration({
    updateStage,
    resetAllStages,
    onComplete: () => { message.success('一键制作完成'); setSseReconnectInfo(null) },
    onError: (msg: string) => { message.error(msg); setSseReconnectInfo(null) },
    onReconnect: (attempt: number, max: number) => {
      setSseReconnectInfo({ attempt, max })
      if (attempt === 1) {
        message.warning({ content: `网络断开，正在重连（${attempt}/${max}）...`, key: 'sse-reconnect', duration: 0 })
      }
    },
  })

  const loadStatus = useCallback(async () => {
    if (!chapterId) return
    const data = await fetchPipelineStatus(chapterId)
    hydrateFromPipelineStatus(data)
  }, [chapterId, hydrateFromPipelineStatus])

  useEffect(() => {
    if (!chapterId) return
    void StudioChaptersService.getChapterApiV1StudioChaptersChapterIdGet({ chapterId }).then((res) => {
      const ch = res.data
      if (ch) {
        setChapterTitle(ch.title || '')
        setScriptText(ch.raw_text || '')
      }
    })
    void loadStatus()
  }, [chapterId, loadStatus])

  const ctx = useMemo(() => ({
    projectId,
    chapterId,
    scriptText,
    setLoading,
    updateStage,
    resetStageForRun,
    poll,
    rememberTaskId: (key: StageKey, taskId: string | null) => {
      taskIdRef.current[key] = taskId
    },
  }), [projectId, chapterId, scriptText, updateStage, resetStageForRun, poll])

  const runners = useMemo(() => buildStageRunners(ctx, {
    chainNext: async (key: StageKey) => {
      if (chainAbortRef.current) return
      await runnersRef.current[key]?.()
    },
  }), [ctx])

  // Keep a ref so chained next-stage calls see the latest runners without
  // rebuilding them on every render (which would reset closures mid-chain).
  const runnersRef = useRef(runners)
  runnersRef.current = runners

  const runStage = useCallback((key: StageKey) => {
    setRunningStage(key)
    chainAbortRef.current = false
    return runnersRef.current[key]()
      .finally(() => setRunningStage((cur) => (cur === key ? null : cur)))
  }, [])

  // C2：Agent SSE 编排（简单章节快速跑，失败控制不精细）
  const runAll = useCallback(async () => {
    if (!projectId || !chapterId || !scriptText) {
      message.error('缺少项目/章节/剧本')
      return
    }
    await orchestrate({ projectId, chapterId, goal: '制作短剧' })
  }, [projectId, chapterId, scriptText, orchestrate])

  // C1：确定性链式跑通（按 STAGE_ORDER 顺序执行，失败按策略暂停或容错）
  const chainRunningRef = useRef(false)
  const [chainPausedAt, setChainPausedAt] = useState<StageKey | null>(null)
  const [chainLog, setChainLog] = useState<{ key: StageKey; ok: boolean; error?: string }[]>([])

  const runChain = useCallback(async () => {
    if (!projectId || !chapterId || !scriptText) {
      message.error('缺少项目/章节/剧本')
      return
    }
    if (chainRunningRef.current) return
    chainRunningRef.current = true
    chainAbortRef.current = false
    setChainPausedAt(null)
    setChainLog([])
    let lastError: string | null = null
    for (const key of STAGE_ORDER) {
      if (chainAbortRef.current) break
      setRunningStage(key)
      const res: ExecResult = await runnersRef.current[key]()
      setChainLog((prev) => [...prev, { key, ok: res.ok, error: res.error }])
      if (!res.ok) {
        if (PAUSE_STAGES.has(key)) {
          // 必须暂停：后续阶段无法跑
          setChainPausedAt(key)
          lastError = res.error || `${key} 失败`
          message.error(`「${STAGE_LABELS[key]}」失败，已暂停：${lastError}。请处理后重新点"一键跑通"继续。`)
          break
        }
        // 可跳过失败：标 partial，继续推进
        message.warning(`「${STAGE_LABELS[key]}」部分失败（${res.error}），已跳过失败项继续推进`)
      }
    }
    setRunningStage(null)
    chainRunningRef.current = false
    if (!chainAbortRef.current && !lastError) {
      message.success('一键跑通完成')
    }
  }, [projectId, chapterId, scriptText])

  const stopChain = useCallback(() => {
    chainAbortRef.current = true
    chainRunningRef.current = false
    setRunningStage(null)
    message.info('已请求停止链式跑通')
  }, [])

  // canRun: a stage is runnable if its predecessor is done (or it's the first).
  const canRun = useCallback((key: StageKey) => {
    const idx = STAGE_ORDER.indexOf(key)
    if (idx <= 0) return true
    const prevKey = STAGE_ORDER[idx - 1]
    const prev = stages.find((s) => s.key === prevKey)
    return prev?.status === 'done'
  }, [stages])

  const allDone = stages.every((s) => s.status === 'done')
  const busy = loading || runningStage !== null || isOrchestrating || chainRunningRef.current

  // 链式跑通整体进度：已完成阶段数 / 总阶段数
  const completedCount = stages.filter((s) => s.status === 'done').length
  const totalCount = STAGE_ORDER.length
  const chainPercent = Math.round((completedCount / totalCount) * 100)
  const chainRunning = chainRunningRef.current

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">一键制作流程</h2>
          <p className="text-sm text-gray-500">{chapterTitle ? `章节: ${chapterTitle}` : ''}</p>
        </div>
        <Space>
          {chainRunning ? (
            <Button danger icon={<CloseCircleOutlined />} onClick={stopChain}>
              停止跑通
            </Button>
          ) : null}
          <Tooltip title="按 6 阶段顺序自动执行；帧图/视频/渲染部分失败自动跳过，资产/分镜失败则暂停">
            <Button
              size="large"
              icon={<ThunderboltOutlined />}
              loading={chainRunning}
              disabled={allDone || !projectId || !chapterId || !scriptText || busy}
              onClick={() => void runChain()}
            >
              {allDone ? '已完成' : chainPausedAt ? '继续跑通' : '一键跑通'}
            </Button>
          </Tooltip>
          <Tooltip title="交给 LLM 决策的 Agent 编排（简单章节快速跑）">
            <Button
              type="primary"
              size="large"
              icon={<ThunderboltOutlined />}
              loading={isOrchestrating}
              disabled={allDone || !projectId || !chapterId || !scriptText || busy}
              onClick={() => void runAll()}
            >
              Agent 编排
            </Button>
          </Tooltip>
        </Space>
      </div>

      {sseReconnectInfo ? (
        <Card size="small" style={{ marginBottom: 12, borderColor: '#ffd591', background: '#fffbe6' }}>
          <Space>
            <Tag color="orange">网络断开</Tag>
            <span className="text-sm">正在重连 SSE（{sseReconnectInfo.attempt}/{sseReconnectInfo.max}）... 已收到的阶段状态保留可见</span>
          </Space>
        </Card>
      ) : null}

      {chainPausedAt ? (
        <Card size="small" style={{ marginBottom: 12, borderColor: '#ffccc7', background: '#fff2f0' }}>
          <Space>
            <Tag color="red">已暂停</Tag>
            <span className="text-sm">卡在「{STAGE_LABELS[chainPausedAt]}」阶段，请处理后重新点"一键跑通"继续</span>
          </Space>
        </Card>
      ) : null}

      {chainRunning || chainLog.length > 0 ? (
        <Card size="small" style={{ marginBottom: 12 }}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">
              {chainRunning ? `正在执行：${runningStage ? STAGE_LABELS[runningStage] : ''}` : '跑通进度'}
            </span>
            <Tag color={chainPausedAt ? 'red' : chainRunning ? 'processing' : 'green'}>
              {completedCount}/{totalCount} 阶段完成
            </Tag>
          </div>
          <Progress percent={chainPercent} status={chainPausedAt ? 'exception' : chainRunning ? 'active' : 'success'} />
          {chainLog.some((l) => !l.ok) ? (
            <div className="mt-2 text-xs text-orange-600">
              {chainLog.filter((l) => !l.ok).map((l) => (
                <div key={l.key}>· 「{STAGE_LABELS[l.key]}」跳过失败项：{l.error}</div>
              ))}
            </div>
          ) : null}
        </Card>
      ) : null}

      <Card>
        <div className="space-y-3">
          {stages.map((stage, i) => {
            // Special-case: asset_images stage keeps the original "去生成/审核"
            // external links to the roles page.
            let externalLink: ReactNode = null
            if (stage.key === 'asset_images' && projectId && canRun('asset_images') && stage.status !== 'done' && stage.status !== 'running' && stage.status !== 'failed') {
              externalLink = (
                <Link to={`/projects/${projectId}?tab=roles`} target="_blank">
                  <Button size="small">去生成</Button>
                </Link>
              )
            } else if (stage.key === 'asset_images' && stage.status === 'done' && projectId) {
              externalLink = (
                <Link to={`/projects/${projectId}?tab=roles`} target="_blank">
                  <Button size="small">审核</Button>
                </Link>
              )
            }

            return (
              <StageCard
                key={stage.key}
                stage={stage}
                index={i}
                canRun={canRun(stage.key)}
                busy={busy}
                externalLink={externalLink}
                onRun={(k) => void runStage(k)}
                projectId={projectId}
                chapterId={chapterId}
              />
            )
          })}
        </div>

       {stages[0].status === 'done' && stages[1].status === 'done' && (
         <Result
           status="info"
           title="资产已就绪"
           subTitle="资产已提取并生成参考图，可以去镜头页生成帧图和视频"
            extra={[
              projectId ? (
                <Link to={`/projects/${projectId}?tab=roles`} key="roles">
                  <Button type="primary">去生成角色图</Button>
                </Link>
              ) : null,
              chapterId && projectId ? (
                <Link to={`/projects/${projectId}/chapters/${chapterId}/shots`} key="shots">
                  <Button>去分镜管理</Button>
                </Link>
              ) : null,
            ]}
            style={{ padding: '12px 0' }}
          />
        )}
      </Card>
    </div>
  )
}
