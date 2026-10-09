/**
 * VideoStagePanel — 视频阶段独立工作面板（P0 落地，2C 第一步：骨架，不含参数编辑）
 *
 * 功能：
 * - 表格列出本章全部 shot：预览缩略图（视频首帧）、镜头标题、视频状态（已生成/未生成/失败）
 * - 批量勾选 + 全选
 * - 「重新生成选中项」→ onRegenerate(selectedIds) → handleStageRun('videos', { onlyIds })
 * - 「重新生成失败项」→ onRegenerate(failedIds)
 * - 单项「重新生成」按钮
 * - 内联预览（点缩略图 → Modal 播放 /api/v1/studio/files/<id>/download）
 * - 区分已生成（绿）/ 未生成（灰）/ 失败（红）
 *
 * 设计沿用 StageCard 的 Antd 风格，务实不花哨（用户 1A 选择）。
 * 参数编辑（prompt/时长/参考图/ratio 表单）留第二轮增量（2C），本版不做。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Modal, Table, Tag, Tooltip, Empty, Spin, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlayCircleOutlined,
  ReloadOutlined,
  VideoCameraOutlined,
  EditOutlined,
} from '@ant-design/icons'
import type { Stage } from '../../types'
import { VideoEditModal } from './VideoEditModal'

type ShotRow = {
  id: string
  index: number
  title: string
  status: string
  script_excerpt?: string
  generated_video_file_id: string | null
}

export type VideoStagePanelProps = {
  chapterId: string | undefined
  stage: Stage
  /** 是否有阶段正在跑（用于禁用操作） */
  busy: boolean
  /** 重新生成指定 shot（onlyIds）；走 video runner → fanOut */
  onRegenerate: (onlyIds: string[]) => void
  /** 中止当前阶段 */
  onStop?: () => void
  /** 项目默认视频比例（从 project.default_video_ratio 读） */
  projectRatio: string
}

/** 视频下载地址：和 StageCard 的 loadStageDetails 同一套约定。 */
function fileDownloadUrl(fileId: string | null): string | null {
  if (!fileId) return null
  return `/api/v1/studio/files/${fileId}/download`
}

export function VideoStagePanel({
  chapterId,
  stage,
  busy,
  onRegenerate,
  onStop,
  projectRatio,
}: VideoStagePanelProps) {
  const [shots, setShots] = useState<ShotRow[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([])
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [editingShot, setEditingShot] = useState<ShotRow | null>(null)

  const isRunning = stage.status === 'running'
  const failedIds = useMemo(
    () => new Set((stage.output?.failedItems ?? []).map((f) => f.id)),
    [stage.output?.failedItems],
  )

  const loadShots = useCallback(async () => {
    if (!chapterId) return
    setLoading(true)
    try {
      const r = await fetch(`/api/v1/studio/shots?chapter_id=${chapterId}&page=1&page_size=100`)
      const d = await r.json()
      const items: any[] = d?.data?.items ?? d?.items ?? []
      setShots(
        items.map((s) => ({
          id: s.id,
          index: s.index,
          title: s.title || '',
          status: s.status || '',
          script_excerpt: s.script_excerpt,
          generated_video_file_id: s.generated_video_file_id ?? null,
        })),
      )
    } catch {
      setShots([])
    } finally {
      setLoading(false)
    }
  }, [chapterId])

  useEffect(() => {
    void loadShots()
  }, [loadShots])

  // 阶段跑完一轮后刷新一次（拿到新的 generated_video_file_id）
  useEffect(() => {
    if (!isRunning && stage.progress >= 100) {
      void loadShots()
    }
  }, [isRunning, stage.progress, loadShots])

  const generatedCount = shots.filter((s) => s.generated_video_file_id).length
  const failedCount = failedIds.size
  const selectedRows = shots.filter((s) => selectedKeys.includes(s.id))
  const selectedGenerated = selectedRows.filter((s) => s.generated_video_file_id).length

  const handleRegenSelected = () => {
    if (!selectedKeys.length) {
      message.warning('请先勾选要重新生成的镜头')
      return
    }
    onRegenerate(selectedKeys as string[])
    setSelectedKeys([])
  }

  const handleRegenFailed = () => {
    const ids = Array.from(failedIds)
    if (!ids.length) {
      message.info('当前没有失败项')
      return
    }
    onRegenerate(ids)
  }

  const columns: ColumnsType<ShotRow> = [
    {
      title: '预览',
      key: 'preview',
      width: 120,
      render: (_, row) => {
        const url = fileDownloadUrl(row.generated_video_file_id)
        if (!url) {
          return (
            <div className="flex items-center justify-center w-[100px] h-[60px] rounded bg-gray-100 text-gray-300">
              <VideoCameraOutlined style={{ fontSize: 20 }} />
            </div>
          )
        }
        return (
          <button
            type="button"
            className="relative w-[100px] h-[60px] rounded overflow-hidden border border-gray-200 hover:border-blue-400 cursor-pointer bg-black"
            onClick={() => setPreviewUrl(url)}
            title="点击预览视频"
          >
            {/* preload=metadata 让浏览器解首帧当封面；9 条量级可接受 */}
            <video
              src={`${url}#t=0.1`}
              preload="metadata"
              muted
              playsInline
              className="w-full h-full object-cover"
              style={{ pointerEvents: 'none' }}
              onLoadedData={(e) => { try { e.currentTarget.currentTime = 0.1 } catch {} }}
            />
            <span className="absolute inset-0 flex items-center justify-center text-white/90">
              <PlayCircleOutlined style={{ fontSize: 20, textShadow: '0 1px 4px rgba(0,0,0,.6)' }} />
            </span>
          </button>
        )
      },
    },
    {
      title: '#',
      dataIndex: 'index',
      width: 48,
      render: (v: number) => <span className="text-gray-500">{v}</span>,
    },
    {
      title: '镜头标题',
      dataIndex: 'title',
      ellipsis: true,
      render: (v: string, row) => (
        <div className="min-w-0">
          <div className="truncate text-sm">{v || '（无标题）'}</div>
          {row.script_excerpt ? (
            <div className="text-xs text-gray-400 truncate">{row.script_excerpt}</div>
          ) : null}
        </div>
      ),
    },
    {
      title: '视频状态',
      key: 'vstatus',
      width: 110,
      render: (_, row) => {
        if (failedIds.has(row.id)) {
          return <Tag color="red">失败</Tag>
        }
        if (row.generated_video_file_id) {
          return <Tag color="green">已生成</Tag>
        }
        return <Tag color="default">未生成</Tag>
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 168,
      render: (_, row) => (
        <div className="flex items-center gap-1">
          <Tooltip title="编辑该镜头的提示词/时长/参考模式/比例后生成">
            <Button
              size="small"
              icon={<EditOutlined />}
              disabled={busy || isRunning}
              onClick={() => setEditingShot(row)}
            >
              编辑
            </Button>
          </Tooltip>
          <Tooltip title={row.generated_video_file_id ? '用现有参数重新生成该镜头' : '生成该镜头视频'}>
            <Button
              size="small"
              icon={<ReloadOutlined />}
              disabled={busy || isRunning}
              onClick={() => onRegenerate([row.id])}
            >
              {row.generated_video_file_id ? '重新' : '生成'}
            </Button>
          </Tooltip>
        </div>
      ),
    },
  ]

  return (
    <div className="mt-3 rounded-lg border border-gray-200 bg-white">
      {/* 顶部操作条 */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100 flex-wrap gap-2">
        <div className="flex items-center gap-2 text-sm">
          <span className="font-medium">视频工作面板</span>
          <Tag color="blue">
            {generatedCount}/{shots.length} 已生成
          </Tag>
          {failedCount > 0 ? (
            <Tag color="red">失败 {failedCount}</Tag>
          ) : null}
          {selectedKeys.length > 0 ? (
            <span className="text-xs text-gray-500">
              已选 {selectedKeys.length}
              {selectedGenerated > 0 ? `（含已生成 ${selectedGenerated}）` : ''}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {isRunning && onStop ? (
            <Button size="small" danger disabled={!busy} onClick={() => onStop()}>
              中止
            </Button>
          ) : null}
          {failedCount > 0 ? (
            <Button
              size="small"
              icon={<ReloadOutlined />}
              disabled={busy || isRunning}
              onClick={handleRegenFailed}
            >
              重新生成失败项（{failedCount}）
            </Button>
          ) : null}
          <Button
            size="small"
            type="primary"
            icon={<ReloadOutlined />}
            disabled={busy || isRunning || !selectedKeys.length}
            onClick={handleRegenSelected}
          >
            重新生成选中（{selectedKeys.length}）
          </Button>
          <Button size="small" onClick={() => void loadShots()} disabled={loading}>
            刷新
          </Button>
        </div>
      </div>

      {/* 表格 */}
      <Table<ShotRow>
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={shots}
        pagination={false}
        scroll={{ y: 360 }}
        rowSelection={{
          selectedRowKeys: selectedKeys,
          onChange: (keys) => setSelectedKeys(keys),
          getCheckboxProps: () => ({ disabled: busy || isRunning }),
        }}
        locale={{
          emptyText: loading ? <Spin tip="加载中…" /> : <Empty description="暂无镜头" />,
        }}
      />

      {/* 内联预览 Modal */}
      <Modal
        open={!!previewUrl}
        onCancel={() => setPreviewUrl(null)}
        footer={null}
        width={420}
        destroyOnClose
        title="视频预览"
      >
        {previewUrl ? (
          <video
            key={previewUrl}
            src={previewUrl}
            controls
            autoPlay
            className="w-full rounded bg-black"
            style={{ maxHeight: '70vh' }}
          />
        ) : null}
      </Modal>

      {/* P0 第二轮：参数编辑表单 */}
      <VideoEditModal
        open={!!editingShot}
        shotId={editingShot?.id ?? null}
        projectRatio={projectRatio}
        shotIndex={editingShot?.index}
        shotTitle={editingShot?.title}
        onClose={() => setEditingShot(null)}
        onSubmitted={() => void loadShots()}
      />
    </div>
  )
}
