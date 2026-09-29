import { useEffect, useState, useCallback } from 'react'
import { Button, Card, message, Spin, Tag, Result } from 'antd'
import { CheckCircleOutlined, ClockCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { FilmService, StudioChaptersService } from '../../../services/generated'
import { useParams, Link } from 'react-router-dom'

const API_BASE = '/api/v1/studio'
const SCRIPT_API = '/api/v1/script-processing'

type StageStatus = 'done' | 'running' | 'not_started' | 'blocked' | 'partial'
type Stage = {
  key: string
  title: string
  desc: string
  status: StageStatus
  actionLabel?: string
}

export default function ChapterPipeline() {
  const { projectId, chapterId } = useParams<{ projectId?: string; chapterId?: string }>()
  const [loading, setLoading] = useState(false)
  const [stages, setStages] = useState<Stage[]>([
    { key: 'asset_extract', title: '\u8d44\u4ea7\u63d0\u53d6', desc: 'LLM \u4ece\u5267\u672c\u63d0\u53d6\u89d2\u8272/\u573a\u666f/\u9053\u5177/\u670d\u88c5', status: 'not_started', actionLabel: '\u5f00\u59cb\u63d0\u53d6' },
    { key: 'asset_images', title: '\u8d44\u4ea7\u56fe\u7247', desc: '\u751f\u6210\u89d2\u8272/\u573a\u666f\u53c2\u8003\u56fe', status: 'not_started' },
    { key: 'divide', title: '\u5206\u955c\u63d0\u53d6', desc: 'LLM \u628a\u5267\u672c\u62c6\u6210\u955c\u5934', status: 'not_started', actionLabel: '\u5f00\u59cb\u5206\u955c' },
    { key: 'bind_assets', title: '\u7ed1\u5b9a\u8d44\u4ea7', desc: '\u5c06\u5df2\u6709\u8d44\u4ea7\u7ed1\u5b9a\u5230\u955c\u5934', status: 'not_started', actionLabel: '\u7ed1\u5b9a\u8d44\u4ea7' },
    { key: 'keyframes', title: '\u955c\u5934\u5e27\u56fe', desc: '\u751f\u6210\u5173\u952e\u5e27', status: 'not_started' },
    { key: 'videos', title: '\u89c6\u9891\u751f\u6210', desc: '\u751f\u6210\u955c\u5934\u89c6\u9891', status: 'not_started' },
    { key: 'render', title: '\u7ae0\u8282\u6e32\u67d3', desc: '\u914d\u97f3+\u5408\u6210\u6210\u7247', status: 'not_started' },
  ])
  const [chapterTitle, setChapterTitle] = useState('')
  const [scriptText, setScriptText] = useState('')
  const [divideResult, setDivideResult] = useState<any>(null)
  const [assetList, setAssetList] = useState<any>(null)

  const loadStatus = useCallback(async () => {
    if (!chapterId) return
    try {
      const res = await fetch(`${API_BASE}/chapters/${chapterId}/pipeline-status`)
      const data = (await res.json())?.data || {}
      setStages(prev => prev.map(s => {
        if (s.key === 'asset_extract') return { ...s, status: data.stage_asset_extract || 'not_started' }
        if (s.key === 'divide') return { ...s, status: data.stage_divide || 'not_started' }
        if (s.key === 'bind_assets') return { ...s, status: data.stage_bind || 'not_started' }
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


  const runAssetExtract = async () => {
    if (!chapterId || !projectId || !scriptText) return
    setLoading(true)
    updateStage('asset_extract', 'running')
    try {
      message.loading({ content: '资产提取中...', key: 'pipe', duration: 0 })
      // Actually use fetch for the new endpoint
      const r = await fetch('/api/v1/script-processing/asset-extract-async', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId, script_text: scriptText }),
      })
      const data = await r.json()
      const tid = data?.data?.task_id
      if (!tid) throw new Error('No task_id')
      await pollTask(tid)
      updateStage('asset_extract', 'done')
      message.success({ content: '资产提取完成', key: 'pipe' })
    } catch (e: any) {
      updateStage('asset_extract', 'not_started')
      message.error({ content: e?.message || '提取失败', key: 'pipe' })
      return
    } finally {
      setLoading(false)
    }
    // Auto-chain: start asset images
    await runAssetImages()
  }

  const runAssetImages = async () => {
    if (!projectId) return
    setLoading(true)
    updateStage('asset_images', 'running')
    try {
      message.loading({ content: '获取资产列表...', key: 'pipe', duration: 0 })
      // Get all characters for the project
      const r = await fetch(`/api/v1/studio/entities/character?project_id=${projectId}`)
      const charsData = await r.json()
      const chars = charsData?.data?.items || charsData?.items || []
      if (!chars.length) {
        updateStage('asset_images', 'done')
        message.info({ content: '没有角色需要生成图片', key: 'pipe' })
        return
      }
      message.loading({ content: `批量生成 ${chars.length} 个角色图片...`, key: 'pipe', duration: 0 })
      const taskIds: string[] = []
      for (const char of chars) {
        try {
          const imgR = await fetch(`/api/v1/studio/image-tasks/characters/${char.id}/image-tasks`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image_id: char.character_images?.[0]?.id || 1, prompt: char.description || char.name }),
          })
          const imgData = await imgR.json()
          if (imgData?.data?.task_id) taskIds.push(imgData.data.task_id)
        } catch {}
      }
      // Poll all tasks
      let completed = 0
      const failed: string[] = []
      for (const tid of taskIds) {
        try {
          await pollTask(tid)
          completed++
          message.loading({ content: `图片生成 ${completed}/${taskIds.length}`, key: 'pipe', duration: 0 })
        } catch {
          failed.push(tid)
        }
      }
      updateStage('asset_images', 'done')
      message.success({ content: `图片完成 ${completed}/${taskIds.length}${failed.length ? ' 失败' + failed.length : ''}`, key: 'pipe' })
    } catch (e: any) {
      updateStage('asset_images', 'not_started')
      message.error({ content: e?.message || '生成失败', key: 'pipe' })
      return
    } finally {
      setLoading(false)
    }
    // Auto-chain: start divide
    await runDivide()
  }

  const runBind = async () => {
    if (!chapterId || !projectId) return
    setLoading(true)
    updateStage('bind', 'running')
    try {
      message.loading({ content: '批量绑定资产...', key: 'pipe', duration: 0 })
      const r = await fetch('/api/v1/studio/chapters/' + chapterId + '/auto-confirm', { method: 'POST' })
      const data = await r.json()?.data || {}
      updateStage('bind', 'done')
      message.success({ content: `绑定完成: 创建${data.created||0} 关联${data.linked||0}`, key: 'pipe' })
    } catch (e: any) {
      updateStage('bind', 'not_started')
      message.error({ content: e?.message || '绑定失败', key: 'pipe' })
      return
    } finally {
      setLoading(false)
    }
    // Auto-chain: start keyframes
    await runKeyframes()
  }

  const runKeyframes = async () => {
    if (!chapterId) return
    setLoading(true)
    updateStage('keyframes', 'running')
    try {
      message.loading({ content: '获取镜头列表...', key: 'pipe', duration: 0 })
      const r = await fetch(`/api/v1/studio/shots?chapter_id=${chapterId}`)
      const shotsData = await r.json()
      const shots = shotsData?.data?.items || shotsData?.items || []
      if (!shots.length) {
        updateStage('keyframes', 'done')
        return
      }
      message.loading({ content: `批量生成 ${shots.length} 个帧图...`, key: 'pipe', duration: 0 })
      const taskIds: string[] = []
      for (const shot of shots) {
        try {
          const fr = await fetch(`/api/v1/studio/image-tasks/shot/${shot.id}/frame-image-tasks`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ frame_type: 'first', model_id: null }),
          })
          const fd = await fr.json()
          if (fd?.data?.task_id) taskIds.push(fd.data.task_id)
        } catch {}
      }
      let completed = 0
      for (const tid of taskIds) {
        try { await pollTask(tid); completed++; message.loading({ content: `帧图 ${completed}/${taskIds.length}`, key: 'pipe', duration: 0 }) } catch {}
      }
      updateStage('keyframes', 'done')
      message.success({ content: `帧图完成 ${completed}/${taskIds.length}`, key: 'pipe' })
    } catch (e: any) {
      updateStage('keyframes', 'not_started')
      message.error({ content: e?.message || '生成失败', key: 'pipe' })
      return
    } finally {
      setLoading(false)
    }
    // Auto-chain: start videos
    await runVideos()
  }

  const runVideos = async () => {
    if (!chapterId) return
    setLoading(true)
    updateStage('videos', 'running')
    try {
      message.loading({ content: '获取镜头列表...', key: 'pipe', duration: 0 })
      const r = await fetch(`/api/v1/studio/shots?chapter_id=${chapterId}`)
      const shotsData = await r.json()
      const shots = shotsData?.data?.items || shotsData?.items || []
      if (!shots.length) { updateStage('videos', 'done'); return }
      message.loading({ content: `批量生成 ${shots.length} 个视频...`, key: 'pipe', duration: 0 })
      const taskIds: string[] = []
      for (const shot of shots) {
        try {
          const vr = await fetch('/api/v1/film/tasks/video', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ shot_id: shot.id, reference_mode: 'text_only', ratio: '16:9', prompt: shot.title || 'scene' }),
          })
          const vd = await vr.json()
          if (vd?.data?.task_id) taskIds.push(vd.data.task_id)
        } catch {}
      }
      let completed = 0
      for (const tid of taskIds) {
        try { await pollTask(tid); completed++; message.loading({ content: `视频 ${completed}/${taskIds.length}`, key: 'pipe', duration: 0 }) } catch {}
      }
      updateStage('videos', 'done')
      message.success({ content: `视频完成 ${completed}/${taskIds.length}`, key: 'pipe' })
    } catch (e: any) {
      updateStage('videos', 'not_started')
      message.error({ content: e?.message || '生成失败', key: 'pipe' })
      return
    } finally {
      setLoading(false)
    }
  }


  const updateStage = (key: string, status: StageStatus) => {
    setStages(prev => prev.map(s => s.key === key ? { ...s, status } : s))
  }

  const runAssetExtract = async () => {
    if (!projectId || !scriptText) return
    setLoading(true)
    updateStage('asset_extract', 'running')
    try {
      message.loading({ content: '\u8d44\u4ea7\u63d0\u53d6\u4e2d...', key: 'pipe', duration: 0 })
      const res = await fetch(`${SCRIPT_API}/asset-extract-async`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId, script_text: scriptText }),
      })
      const data = (await res.json())?.data || {}
      const tid = data.task_id
      if (!tid) throw new Error('No task_id')
      const result = await pollTask(tid)
      setAssetList(result)
      updateStage('asset_extract', 'done')
      message.success({ content: '\u8d44\u4ea7\u63d0\u53d6\u5b8c\u6210', key: 'pipe' })
      await loadStatus()
    } catch (e: any) {
      updateStage('asset_extract', 'not_started')
      message.error({ content: e?.message || '\u63d0\u53d6\u5931\u8d25', key: 'pipe' })
    } finally {
      setLoading(false)
    }
  }

  const runDivide = async () => {
    if (!chapterId || !scriptText) return
    setLoading(true)
    updateStage('divide', 'running')
    try {
      message.loading({ content: '\u5206\u955c\u63d0\u53d6\u4e2d...', key: 'pipe', duration: 0 })
      const res = await fetch(`${SCRIPT_API}/divide-async`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ script_text: scriptText, write_to_db: true, chapter_id: chapterId }),
      })
      const data = (await res.json())?.data || {}
      const tid = data.task_id
      if (!tid) throw new Error('No task_id')
      const result = await pollTask(tid)
      setDivideResult(result)
      updateStage('divide', 'done')
      message.success({ content: '\u5206\u955c\u5b8c\u6210', key: 'pipe' })
      await loadStatus()
    } catch (e: any) {
      updateStage('divide', 'not_started')
      message.error({ content: e?.message || '\u5206\u955c\u5931\u8d25', key: 'pipe' })
    } finally {
      setLoading(false)
    }
  }

  const runBindAssets = async () => {
    if (!chapterId) return
    setLoading(true)
    updateStage('bind_assets', 'running')
    try {
      message.loading({ content: '\u7ed1\u5b9a\u8d44\u4ea7\u4e2d...', key: 'pipe', duration: 0 })
      let division = divideResult
      if (!division) {
        const tasksRes = await fetch(`/api/v1/film/tasks?task_kind=script_divide&page=1&page_size=1`)
        const tasksData = (await tasksRes.json())?.data
        const tasks = tasksData?.items || []
        const succeededTask = tasks.find((t: any) => t.status === 'succeeded')
        if (succeededTask) {
          const resultRes = await fetch(`/api/v1/film/tasks/${succeededTask.id}/result`)
          division = (await resultRes.json())?.data
        }
      }
      if (!division) throw new Error('\u8bf7\u5148\u5b8c\u6210\u5206\u955c\u63d0\u53d6')
      let assets = assetList
      if (!assets) {
        const tasksRes = await fetch(`/api/v1/film/tasks?task_kind=script_asset_extract&page=1&page_size=1`)
        const tasksData = (await tasksRes.json())?.data
        const tasks = tasksData?.items || []
        const succeededTask = tasks.find((t: any) => t.status === 'succeeded')
        if (succeededTask) {
          const resultRes = await fetch(`/api/v1/film/tasks/${succeededTask.id}/result`)
          assets = (await resultRes.json())?.data?.result || (await resultRes.json())?.data
        }
      }
      if (!assets) throw new Error('\u8bf7\u5148\u5b8c\u6210\u8d44\u4ea7\u63d0\u53d6')
      const divisionData = division?.result || division
      const res = await fetch(`${SCRIPT_API}/bind-assets-async`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          chapter_id: chapterId,
          script_division_json: JSON.stringify(divisionData),
          asset_list_json: JSON.stringify(assets),
        }),
      })
      const data = (await res.json())?.data || {}
      const tid = data.task_id
      if (!tid) throw new Error('No task_id')
      await pollTask(tid)
      updateStage('bind_assets', 'done')
      message.success({ content: '\u8d44\u4ea7\u7ed1\u5b9a\u5b8c\u6210', key: 'pipe' })
      await loadStatus()
    } catch (e: any) {
      updateStage('bind_assets', 'not_started')
      message.error({ content: e?.message || '\u7ed1\u5b9a\u5931\u8d25', key: 'pipe' })
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
      done: { color: 'green', text: '\u5df2\u5b8c\u6210' },
      running: { color: 'blue', text: '\u8fdb\u884c\u4e2d' },
      partial: { color: 'orange', text: '\u90e8\u5206\u5b8c\u6210' },
      not_started: { color: 'default', text: '\u672a\u5f00\u59cb' },
      blocked: { color: 'red', text: '\u963b\u585e' },
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
    if (key === 'asset_extract') return runAssetExtract()
    if (key === 'asset_extract') return runAssetExtract()
    if (key === 'asset_images') return runAssetImages()
    if (key === 'divide') return runDivide()
    if (key === 'bind') return runBind()
    if (key === 'keyframes') return runKeyframes()
    if (key === 'videos') return runVideos()
    if (key === 'bind_assets') return runBindAssets()
    message.info('\u8be5\u9636\u6bb5\u8bf7\u5728\u5bf9\u5e94\u9875\u9762\u64cd\u4f5c')
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-4">
        <h2 className="text-lg font-semibold">{'\u4e00\u952e\u5236\u4f5c\u6d41\u7a0b'}</h2>
        <p className="text-sm text-gray-500">{chapterTitle ? `\u7ae0\u8282: ${chapterTitle}` : ''}</p>
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
                {stage.key === 'asset_images' && canRun(stage.key) && stage.status !== 'done' && projectId && (
                  <>
                    <Link to={`/projects/${projectId}?tab=roles`} target="_blank">
                      <Button size="small" type="primary">{'\u53bb\u751f\u6210'}</Button>
                    </Link>
                    <Button size="small" onClick={() => updateStage('asset_images', 'done')}>{'\u5b8c\u6210'}</Button>
                  </>
                )}
                {stage.key === 'asset_images' && stage.status === 'done' && projectId && (
                  <Link to={`/projects/${projectId}?tab=roles`} target="_blank">
                    <Button size="small" icon={<ReloadOutlined />}>{'\u5ba1\u6838'}</Button>
                  </Link>
                )}
                {stage.key === 'bind_assets' && stage.status === 'done' && (
                  <Tag color="green">{'\u53ef\u5ba1\u6838'}</Tag>
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

        {stages[0].status === 'done' && stages[3].status === 'done' && (
          <Result
            status="info"
            title={'\u8d44\u4ea7\u5df2\u5c31\u7eea'}
            subTitle={'\u8d44\u4ea7\u5df2\u63d0\u53d6\u5e76\u7ed1\u5b9a\u5230\u955c\u5934\uff0c\u53ef\u4ee5\u53bb\u955c\u5934\u9875\u751f\u6210\u5e27\u56fe\u548c\u89c6\u9891'}
            extra={[
              projectId ? (
                <Link to={`/projects/${projectId}?tab=roles`}>
                  <Button type="primary">{'\u53bb\u751f\u6210\u89d2\u8272\u56fe'}</Button>
                </Link>
              ) : null,
              chapterId ? (
                <Link to={`/projects/${projectId}/chapters/${chapterId}/shots`}>
                  <Button>{'\u53bb\u5206\u955c\u7ba1\u7406'}</Button>
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
