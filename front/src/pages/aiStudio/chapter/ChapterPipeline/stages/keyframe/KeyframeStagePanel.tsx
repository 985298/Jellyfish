import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Modal, Table, Tag, Tooltip, Empty, Spin, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlayCircleOutlined, ReloadOutlined, EditOutlined } from '@ant-design/icons'
import type { Stage } from '../../types'
import { KeyframeEditModal } from './KeyframeEditModal'

type ShotRow = { id: string; index: number; title: string; status: string; script_excerpt?: string; generated_frame_file_id: string | null }

export type KeyframeStagePanelProps = {
  chapterId: string | undefined
  stage: Stage
  busy: boolean
  onRegenerate: (onlyIds: string[]) => void
  onStop?: () => void
}

function frameUrl(fid: string | null) { return fid ? `/api/v1/studio/files/${fid}/download` : null }

export function KeyframeStagePanel({ chapterId, stage, busy, onRegenerate, onStop }: KeyframeStagePanelProps) {
  const [shots, setShots] = useState<ShotRow[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([])
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [editingShot, setEditingShot] = useState<ShotRow | null>(null)

  const isRunning = stage.status === 'running'
  const failedIds = useMemo(() => new Set((stage.output?.failedItems ?? []).map((f) => f.id)), [stage.output?.failedItems])

  const loadShots = useCallback(async () => {
    if (!chapterId) return
    setLoading(true)
    try {
      const r = await fetch(`/api/v1/studio/shots?chapter_id=${chapterId}&page=1&page_size=100`)
      const d = await r.json()
      const items: any[] = d?.data?.items ?? d?.items ?? []
      const fidByShot = new Map<string, string>()
      try {
        const fr = await fetch(`/api/v1/studio/shot-frame-images?shot_detail_id=${chapterId.split(',').map(()=>'').join('')}&page=1&page_size=100`)
        const fd = await fr.json()
        const fitems: any[] = fd?.data?.items ?? fd?.items ?? []
        for (const it of fitems) if (it.shot_detail_id && it.file_id) fidByShot.set(it.shot_detail_id, it.file_id)
      } catch {}
      setShots(items.map((s) => ({
        id: s.id, index: s.index, title: s.title || '', status: s.status || '',
        script_excerpt: s.script_excerpt,
        generated_frame_file_id: fidByShot.get(s.id) ?? null,
      })))
    } catch { setShots([]) }
    finally { setLoading(false) }
  }, [chapterId])

  useEffect(() => { void loadShots() }, [loadShots])
  useEffect(() => { if (!isRunning && stage.progress >= 100) void loadShots() }, [isRunning, stage.progress, loadShots])

  const generatedCount = shots.filter((s) => s.generated_frame_file_id).length
  const failedCount = failedIds.size

  const handleRegenSelected = () => {
    if (!selectedKeys.length) { message.warning('请先勾选镜头'); return }
    onRegenerate(selectedKeys as string[]); setSelectedKeys([])
  }
  const handleRegenFailed = () => {
    const ids = Array.from(failedIds)
    if (!ids.length) { message.info('没有失败项'); return }
    onRegenerate(ids)
  }

  const columns: ColumnsType<ShotRow> = [
    { title: '预览', key: 'preview', width: 120, render: (_, row) => {
      const url = frameUrl(row.generated_frame_file_id)
      if (!url) return <div className="flex items-center justify-center w-[100px] h-[60px] rounded bg-gray-100 text-gray-300"><PlayCircleOutlined style={{ fontSize: 20 }} /></div>
      return <button type="button" className="relative w-[100px] h-[60px] rounded overflow-hidden border border-gray-200 hover:border-blue-400 cursor-pointer bg-black" onClick={() => setPreviewUrl(url)} title="点击预览首帧">
        <img src={`${url}#t=0.1`} alt="首帧" className="w-full h-full object-cover" loading="lazy" />
        <span className="absolute inset-0 flex items-center justify-center text-white/90"><PlayCircleOutlined style={{ fontSize: 20, textShadow: '0 1px 4px rgba(0,0,0,.6)' }} /></span>
      </button>
    }},
    { title: '#', dataIndex: 'index', width: 48, render: (v: number) => <span className="text-gray-500">{v}</span> },
    { title: '镜头标题', dataIndex: 'title', ellipsis: true, render: (v: string, row) => (
      <div className="min-w-0"><div className="truncate text-sm">{v || '（无标题）'}</div>
        {row.script_excerpt ? <div className="text-xs text-gray-400 truncate">{row.script_excerpt}</div> : null}</div>
    )},
    { title: '帧图状态', key: 'fstatus', width: 110, render: (_, row) => (
      failedIds.has(row.id) ? <Tag color="red">失败</Tag>
      : row.generated_frame_file_id ? <Tag color="green">已生成</Tag>
      : <Tag color="default">未生成</Tag>
    )},
    { title: '操作', key: 'action', width: 168, render: (_, row) => (
      <div className="flex items-center gap-1">
        <Tooltip title="编辑帧类型/提示词后生成">
          <Button size="small" icon={<EditOutlined />} disabled={busy || isRunning} onClick={() => setEditingShot(row)}>编辑</Button>
        </Tooltip>
        <Tooltip title={row.generated_frame_file_id ? '用现有参数重新生成首帧' : '生成首帧'}>
          <Button size="small" icon={<ReloadOutlined />} disabled={busy || isRunning} onClick={() => onRegenerate([row.id])}>
            {row.generated_frame_file_id ? '重新' : '生成'}
          </Button>
        </Tooltip>
      </div>
    )},
  ]

  return (
    <div className="mt-3 rounded-lg border border-gray-200 bg-white">
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100 flex-wrap gap-2">
        <div className="flex items-center gap-2 text-sm">
          <span className="font-medium">帧图工作面板</span>
          <Tag color="blue">{generatedCount}/{shots.length} 已生成</Tag>
          {failedCount > 0 ? <Tag color="red">失败 {failedCount}</Tag> : null}
          {selectedKeys.length > 0 ? <span className="text-xs text-gray-500">已选 {selectedKeys.length}</span> : null}
        </div>
        <div className="flex items-center gap-2">
          {isRunning && onStop ? <Button size="small" danger disabled={!busy} onClick={() => onStop()}>中止</Button> : null}
          {failedCount > 0 ? <Button size="small" icon={<ReloadOutlined />} disabled={busy || isRunning} onClick={handleRegenFailed}>重新生成失败项（{failedCount}）</Button> : null}
          <Button size="small" type="primary" icon={<ReloadOutlined />} disabled={busy || isRunning || !selectedKeys.length} onClick={handleRegenSelected}>重新生成选中（{selectedKeys.length}）</Button>
          <Button size="small" onClick={() => void loadShots()} disabled={loading}>刷新</Button>
        </div>
      </div>
      <Table<ShotRow> rowKey="id" size="small" loading={loading} columns={columns} dataSource={shots} pagination={false} scroll={{ y: 360 }}
        rowSelection={{ selectedRowKeys: selectedKeys, onChange: (keys) => setSelectedKeys(keys), getCheckboxProps: () => ({ disabled: busy || isRunning }) }}
        locale={{ emptyText: loading ? <Spin tip="加载中…" /> : <Empty description="暂无镜头" /> }} />
      <Modal open={!!previewUrl} onCancel={() => setPreviewUrl(null)} footer={null} width={420} destroyOnClose title="首帧预览">
        {previewUrl ? <img src={previewUrl} className="w-full rounded bg-black" style={{ maxHeight: '70vh' }} /> : null}
      </Modal>
      <KeyframeEditModal
        open={!!editingShot}
        shotId={editingShot?.id ?? null}
        shotIndex={editingShot?.index}
        shotTitle={editingShot?.title}
        defaultPrompt={editingShot?.script_excerpt}
        onClose={() => setEditingShot(null)}
        onSubmitted={() => void loadShots()}
      />
    </div>
  )
}
