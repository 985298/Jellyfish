import { useEffect, useState, useCallback } from 'react'
import { Button, Card, Steps, message, Spin, Tag, Space, Result } from 'antd'
import { CheckCircleOutlined, ClockCircleOutlined, PlayCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { ScriptProcessingService, FilmService, StudioChaptersService } from '../../../services/generated'
import { useParams, Link } from 'react-router-dom'

const API_BASE = '/api/v1/studio'

type StageStatus = 'done' | 'running' | 'not_started' | 'blocked' | 'partial'
type Stage = {
  key: string
  title: string
  desc: string
  status: StageStatus
  actionLabel?: string
  reviewLink?: string
}

export default function ChapterPipeline() {
  const { projectId, chapterId } = useParams<{ projectId?: string; chapterId?: string }>()
  const [loading, setLoading] = useState(false)
  const [stages, setStages] = useState<Stage[]>([
    { key: 'divide', title: '分镜提取', desc: 'LLM 把剧本拆成镜头', status: 'not_started', actionLabel: '开始分镜' },
    { key: 'extract', title: '元素提取', desc: '从镜头中提取角色/场景/道具', status: 'not_started', actionLabel: '开始提取' },
    { key: 'confirm', title: '候选确认', desc: '自动创建实体+关联', status: 'not_started', actionLabel: '一键确认' },
    { key: 'asset_images', title: '资产图片', desc: '生成角色/场景参考图', status: 'not_started', reviewLink: 'review' },
    { key: 'keyframes', title: '镜头帧图', desc: '生成关键帧', status: 'not_started' },
    { key: 'videos', title: '视频生成', desc: '生成镜头视频', status: 'not_started' },
    { key: 'render', title: '章节渲染', desc: '配音+合成成片', status: 'not_started' },
  ])
  const [chapterTitle, setChapterTitle] = useState('')
  const [scriptText, setScriptText] = useState('')

  const loadStatus = useCallback(async () => {
    if (!chapterId) return
    try {
      const res = await fetch(`${API_BASE}/chapters/${chapterId}/pipeline-status`)
      const data = (await res.json())?.data || {}
      setStages(prev => prev.map(s => {
        if (s.key === 'divide') return { ...s, status: data.stage_divide || 'not_started' }
        if (s.key === 'extract') return { ...s, status: data.stage_extract || 'not_started' }
        if (s.key === 'confirm') return { ...s, status: data.stage_confirm || 'not_started' }
        return s
      }))
    } catch {}
  }, [chapterId])

  useEffect(() => {
    if (!chapterId) return
    StudioChaptersService.getChapterApiV1StudioChaptersChapterIdGet({ chapterId }).then(res => {
      const ch = res.data
      if (ch) {
        setChapterTitle(ch.title || '')
        setScriptText(ch.raw_text || '')
      }
    })
    void loadStatus()
  }, [chapterId, loadStatus])

  const pollTask = async (taskId: string): Promise<any> => {
    for (let i = 0; i < 100; i++) {
      await new Promise(r => setTimeout(r, 3000))
      const res = await FilmService.getTaskStatusApiV1FilmTasksTaskIdStatusGet({ taskId })
      const st = res.data?.status
      if (st === 'succeeded') {
        const rr = await FilmService.getTaskResultApiV1FilmTasksTaskIdResultGet({ taskId })
        return rr.data
      }
      if (st === 'failed' || st === 'error' || st === 'cancelled') {
        throw new Error(String(res.data?.error || `Task ${st}`))
      }
    }
    throw new Error('Timeout')
  }

  const updateStage = (key: string, status: StageStatus) => {
    setStages(prev => prev.map(s => s.key === key ? { ...s, status } : s))
  }

  const runDivide = async () => {
    if (!chapterId || !scriptText) return
    setLoading(true)
    updateStage('divide', 'running')
    try {
      message.loading({ content: '分镜提取中...', key: 'pipe', duration: 0 })
      const res = await ScriptProcessingService.divideScriptAsyncApiV1ScriptProcessingDivideAsyncPost({
        requestBody: { script_text: scriptText, write_to_db: true, chapter_id: chapterId },
      })
      const tid = res.data?.task_id
      if (!tid) throw new Error('No task_id')
      await pollTask(tid)
      updateStage('divide', 'done')
      message.success({ content: '分镜完成', key: 'pipe' })
      await loadStatus()
    } catch (e: any) {
      updateStage('divide', 'not_started')
      message.error({ content: e?.message || '分镜失败', key: 'pipe' })
    } finally {
      setLoading(false)
    }
  }

  const runExtract = async () => {
    if (!chapterId || !projectId) return
    setLoading(true)
    updateStage('extract', 'running')
    try {
      message.loading({ content: '元素提取中...', key: 'pipe', duration: 0 })
      // Get shots first
      const shotsRes = await fetch(`${API_BASE}/shots?chapter_id=${chapterId}&page=1&page_size=100`)
      const shotsData = (await shotsRes.json())?.data
      const shots = shotsData?.items || []
      if (!shots.length) throw new Error('No shots found')
      // Extract for each shot (use first shot's division)
      const divideRes = await fetch(`${API_BASE}/chapters/${chapterId}/shots`)
      // Actually, extract needs script_division - get from divide task result
      // For simplicity, extract from the first shot's data
      const firstShot = shots[0]
      const extractRes = await ScriptProcessingService.extractScriptAsyncApiV1ScriptProcessingExtractAsyncPost({
        requestBody: {
          project_id: projectId,
          chapter_id: chapterId,
          script_division: { shots: shots.map((s: any) => ({ index: s.index, start_line: 1, end_line: 1, script_excerpt: s.script_excerpt || '', shot_name: s.title || '' })) },
          consistency: null,
        },
      })
      const tid = extractRes.data?.task_id
      if (!tid) throw new Error('No task_id')
      await pollTask(tid)
      updateStage('extract', 'done')
      message.success({ content: '元素提取完成', key: 'pipe' })
      await loadStatus()
    } catch (e: any) {
      updateStage('extract', 'not_started')
      message.error({ content: e?.message || '提取失败', key: 'pipe' })
    } finally {
      setLoading(false)
    }
  }

  const runAutoConfirm = async () => {
    if (!chapterId) return
    setLoading(true)
    updateStage('confirm', 'running')
    try {
      message.loading({ content: '自动确认候选中...', key: 'pipe', duration: 0 })
      const res = await fetch(`${API_BASE}/chapters/${chapterId}/auto-confirm`, { method: 'POST' })
      const data = (await res.json())?.data || {}
      updateStage('confirm', 'done')
      message.success({ content: `确认完成: 创建${data.created} 关联${data.linked}`, key: 'pipe' })
      await loadStatus()
    } catch (e: any) {
      updateStage('confirm', 'not_started')
      message.error({ content: e?.message || '确认失败', key: 'pipe' })
    } finally {
      setLoading(false)
    }
  }

  const statusIcon = (status: StageStatus) => {
    switch (status) {
      case 'done': return <CheckCircleOutlined style={{ color: '#52c41a' }} />
      case 'running': return <Spin size="small" />
      case 'partial': return <ClockCircleOutlined style={{ color: '#faad14' }} />
      case 'blocked': return <ClockCircleOutlined style={{ color: '#d9d9d9' }} />
      default: return <ClockCircleOutlined style={{ color: '#d9d9d9' }} />
    }
  }

  const statusTag = (status: StageStatus) => {
    const map: Record<string, { color: string; text: string }> = {
      done: { color: 'green', text: '已完成' },
      running: { color: 'blue', text: '进行中' },
      partial: { color: 'orange', text: '部分完成' },
      not_started: { color: 'default', text: '未开始' },
      blocked: { color: 'red', text: '阻塞' },
    }
    const s = map[status] || map.not_started
    return <Tag color={s.color}>{s.text}</Tag>
  }

  const canRun = (key: string) => {
    const idx = stages.findIndex(s => s.key === key)
    if (idx === 0) return true
    return stages[idx - 1].status === 'done'
  }

  const runStage = (key: string) => {
    if (key === 'divide') return runDivide()
    if (key === 'extract') return runExtract()
    if (key === 'confirm') return runAutoConfirm()
    message.info('该阶段请在对应页面操作')
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-4">
        <h2 className="text-lg font-semibold">一键制作流程</h2>
        <p className="text-sm text-gray-500">{chapterTitle ? `章节: ${chapterTitle}` : ''}</p>
      </div>

      <Card>
        <div className="space-y-3">
          {stages.map((stage, i) => (
            <div key={stage.key} className="flex items-center justify-between p-3 rounded-lg border border-gray-200">
              <div className="flex items-center gap-3">
                <div className="text-lg">{statusIcon(stage.status)}</div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm">{i + 1}. {stage.title}</span>
                    {statusTag(stage.status)}
                  </div>
                  <div className="text-xs text-gray-500 mt-0.5">{stage.desc}</div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {stage.key === 'asset_images' && stage.status === 'done' && projectId && (
                  <Link to={`/projects/${projectId}?tab=roles`}>
                    <Button size="small" icon={<ReloadOutlined />}>审核资产</Button>
                  </Link>
                )}
                {stage.key === 'confirm' && stage.status === 'done' && (
                  <Tag color="green">可审核</Tag>
                )}
                {stage.actionLabel && stage.status !== 'done' && stage.status !== 'running' && (
                  <Button
                    size="small"
                    type="primary"
                    disabled={loading || !canRun(stage.key)}
                    onClick={() => runStage(stage.key)}
                  >
                    {stage.actionLabel}
                  </Button>
                )}
                {stage.status === 'running' && (
                  <Spin size="small" />
                )}
              </div>
            </div>
          ))}
        </div>

        {stages[0].status === 'done' && stages[2].status === 'done' && (
          <Result
            status="info"
            title="资产已就绪"
            subTitle="候选已确认，可以去角色/场景管理页生成参考图，然后回到镜头页生成帧图和视频"
            extra={[
              projectId ? (
                <Link to={`/projects/${projectId}?tab=roles`}>
                  <Button type="primary">去生成角色图</Button>
                </Link>
              ) : null,
              chapterId ? (
                <Link to={`/projects/${projectId}/chapters/${chapterId}/shots`}>
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
