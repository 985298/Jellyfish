import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Button, Card, Result, message } from 'antd'
import { ThunderboltOutlined } from '@ant-design/icons'
import { StudioChaptersService } from '../../../services/generated'
import { useParams, Link } from 'react-router-dom'
import { StageCard } from './ChapterPipeline/StageCard'
import { usePipelineState, useTaskPolling, fetchPipelineStatus } from './ChapterPipeline/usePipelineState'
import { buildStageRunners, STAGE_ORDER } from './ChapterPipeline/pipelineStages'
import type { Stage, StageKey } from './ChapterPipeline/types'

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
    desc: '生成角色/场景参考图',
    status: 'not_started',
    progress: 0,
    actionLabel: '执行',
  },
  {
    key: 'divide',
    title: '分镜提取',
    desc: 'LLM 把剧本拆成镜头',
    status: 'not_started',
    progress: 0,
    actionLabel: '执行',
  },
  {
    key: 'bind_assets',
    title: '绑定资产',
    desc: '将已有资产绑定到镜头',
    status: 'not_started',
    progress: 0,
    actionLabel: '执行',
  },
  {
    key: 'keyframes',
    title: '镜头帧图',
    desc: '生成关键帧',
    status: 'not_started',
    progress: 0,
    actionLabel: '执行',
  },
  {
    key: 'videos',
    title: '视频生成',
    desc: '生成镜头视频',
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

  const { stages, updateStage, resetStageForRun, hydrateFromPipelineStatus } = usePipelineState(INITIAL_STAGES)
  const { poll } = useTaskPolling()

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

  const runAll = useCallback(async () => {
    if (!projectId || !chapterId || !scriptText) {
      message.error('缺少项目/章节/剧本')
      return
    }
    chainAbortRef.current = false
    let lastOk = true
    for (const key of STAGE_ORDER) {
      if (chainAbortRef.current) break
      setRunningStage(key)
      const res = await runnersRef.current[key]()
      lastOk = res.ok
      if (!lastOk) break
    }
    setRunningStage(null)
    if (lastOk) message.success('一键制作完成')
  }, [projectId, chapterId, scriptText])

  // canRun: a stage is runnable if its predecessor is done (or it's the first).
  const canRun = useCallback((key: StageKey) => {
    const idx = STAGE_ORDER.indexOf(key)
    if (idx <= 0) return true
    const prevKey = STAGE_ORDER[idx - 1]
    const prev = stages.find((s) => s.key === prevKey)
    return prev?.status === 'done'
  }, [stages])

  const allDone = stages.every((s) => s.status === 'done')
  const busy = loading || runningStage !== null

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">一键制作流程</h2>
          <p className="text-sm text-gray-500">{chapterTitle ? `章节: ${chapterTitle}` : ''}</p>
        </div>
        <Button
          type="primary"
          size="large"
          icon={<ThunderboltOutlined />}
          loading={busy}
          disabled={allDone || !projectId || !chapterId || !scriptText}
          onClick={() => void runAll()}
        >
          {allDone ? '已完成' : '一键开始'}
        </Button>
      </div>

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
              />
            )
          })}
        </div>

        {stages[0].status === 'done' && stages[3].status === 'done' && (
          <Result
            status="info"
            title="资产已就绪"
            subTitle="资产已提取并绑定到镜头，可以去镜头页生成帧图和视频"
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
