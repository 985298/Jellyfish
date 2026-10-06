/**
 * AssetImageStagePanel — 资产图片阶段工作面板（P0，复用 video 模式）
 * target=character 实体，缩略图=character_images[0].file_id，重新生成走 runStage('asset_images',{onlyIds})
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Modal, Table, Tag, Tooltip, Empty, Spin, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { UserOutlined, ReloadOutlined } from '@ant-design/icons'
import type { Stage } from '../../types'

type CharRow = {
  id: string
  name: string
  description?: string
  style?: string
  thumbnail_file_id: string | null
  image_count: number
}

export type AssetImageStagePanelProps = {
  projectId: string | undefined
  stage: Stage
  busy: boolean
  onRegenerate: (onlyIds: string[]) => void
  onStop?: () => void
}

function fileUrl(fid: string | null) { return fid ? `/api/v1/studio/files/${fid}/download` : null }

export function AssetImageStagePanel({ projectId, stage, busy, onRegenerate, onStop }: AssetImageStagePanelProps) {
  const [rows, setRows] = useState<CharRow[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([])
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)

  const isRunning = stage.status === 'running'
  const failedIds = useMemo(() => new Set((stage.output?.failedItems ?? []).map((f) => f.id)), [stage.output?.failedItems])

  const load = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const r = await fetch(`/api/v1/studio/entities/character?project_id=${projectId}&page=1&page_size=100`)
      const d = await r.json()
      const items: any[] = d?.data?.items ?? d?.items ?? []
      setRows(items.map((c) => {
        const imgs = c.character_images ?? []
        const primary = imgs.find((i: any) => i.is_primary) ?? imgs[0]
        return {
          id: c.id, name: c.name || c.id, description: c.description, style: c.style,
          thumbnail_file_id: primary?.file_id ?? null,
          image_count: imgs.length,
        }
      }))
    } catch { setRows([]) }
    finally { setLoading(false) }
  }, [projectId])

  useEffect(() => { void load() }, [load])
  useEffect(() => { if (!isRunning && stage.progress >= 100) void load() }, [isRunning, stage.progress, load])

  const generatedCount = rows.filter((r) => r.thumbnail_file_id).length
  const failedCount = failedIds.size

  const handleRegenSelected = () => {
    if (!selectedKeys.length) { message.warning('请先勾选角色'); return }
    onRegenerate(selectedKeys as string[]); setSelectedKeys([])
  }
  const handleRegenFailed = () => {
    const ids = Array.from(failedIds)
    if (!ids.length) { message.info('没有失败项'); return }
    onRegenerate(ids)
  }

  const columns: ColumnsType<CharRow> = [
    {
      title: '预览', key: 'preview', width: 84,
      render: (_, row) => {
        const url = fileUrl(row.thumbnail_file_id)
        if (!url) return <div className="flex items-center justify-center w-[64px] h-[64px] rounded-full bg-gray-100 text-gray-300"><UserOutlined style={{ fontSize: 24 }} /></div>
        return (
          <button type="button" className="w-[64px] h-[64px] rounded-full overflow-hidden border-2 border-gray-200 hover:border-blue-400 cursor-pointer bg-gray-100"
            onClick={() => setPreviewUrl(url)} title="点击预览">
            <img src={url} alt={row.name} className="w-full h-full object-cover" loading="lazy" />
          </button>
        )
      },
    },
    { title: '角色', dataIndex: 'name', ellipsis: true, render: (v: string, row) => (
      <div className="min-w-0"><div className="truncate text-sm font-medium">{v}</div>
        {row.description ? <div className="text-xs text-gray-400 truncate">{row.description.slice(0,60)}</div> : null}</div>
    ) },
    { title: '风格', dataIndex: 'style', width: 90, render: (v: string) => v ? <Tag>{v}</Tag> : <span className="text-gray-300">—</span> },
    { title: '图片数', key: 'imgcount', width: 70, render: (_, row) => <span className={row.image_count ? 'text-gray-700' : 'text-gray-300'}>{row.image_count}</span> },
    { title: '状态', key: 'status', width: 110, render: (_, row) => (
      failedIds.has(row.id) ? <Tag color="red">失败</Tag>
      : row.thumbnail_file_id ? <Tag color="green">已生成</Tag>
      : <Tag color="default">未生成</Tag>
    ) },
    { title: '操作', key: 'action', width: 110, render: (_, row) => (
      <Tooltip title={row.thumbnail_file_id ? '用现有参数重新生成角色图' : '生成角色图'}>
        <Button size="small" icon={<ReloadOutlined />} disabled={busy || isRunning} onClick={() => onRegenerate([row.id])}>
          {row.thumbnail_file_id ? '重新生成' : '生成'}
        </Button>
      </Tooltip>
    ) },
  ]

  return (
    <div className="mt-3 rounded-lg border border-gray-200 bg-white">
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100 flex-wrap gap-2">
        <div className="flex items-center gap-2 text-sm">
          <span className="font-medium">资产图片工作面板</span>
          <Tag color="blue">{generatedCount}/{rows.length} 已生成</Tag>
          {failedCount > 0 ? <Tag color="red">失败 {failedCount}</Tag> : null}
          {selectedKeys.length > 0 ? <span className="text-xs text-gray-500">已选 {selectedKeys.length}</span> : null}
        </div>
        <div className="flex items-center gap-2">
          {isRunning && onStop ? <Button size="small" danger disabled={!busy} onClick={() => onStop()}>中止</Button> : null}
          {failedCount > 0 ? <Button size="small" icon={<ReloadOutlined />} disabled={busy || isRunning} onClick={handleRegenFailed}>重新生成失败项（{failedCount}）</Button> : null}
          <Button size="small" type="primary" icon={<ReloadOutlined />} disabled={busy || isRunning || !selectedKeys.length} onClick={handleRegenSelected}>重新生成选中（{selectedKeys.length}）</Button>
          <Button size="small" onClick={() => void load()} disabled={loading}>刷新</Button>
        </div>
      </div>
      <Table<CharRow> rowKey="id" size="small" loading={loading} columns={columns} dataSource={rows} pagination={false} scroll={{ y: 360 }}
        rowSelection={{ selectedRowKeys: selectedKeys, onChange: (keys) => setSelectedKeys(keys), getCheckboxProps: () => ({ disabled: busy || isRunning }) }}
        locale={{ emptyText: loading ? <Spin tip="加载中…" /> : <Empty description="暂无角色" /> }} />
      <Modal open={!!previewUrl} onCancel={() => setPreviewUrl(null)} footer={null} width={420} destroyOnClose title="角色图预览">
        {previewUrl ? <img src={previewUrl} className="w-full rounded bg-black" style={{ maxHeight: '70vh' }} /> : null}
      </Modal>
    </div>
  )
}
