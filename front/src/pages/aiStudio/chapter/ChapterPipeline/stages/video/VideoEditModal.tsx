/**
 * VideoEditModal — 视频阶段参数编辑表单（P0 第二轮，2C→A）
 *
 * 字段：prompt / 时长 / reference_mode / ratio
 * 提交流程：
 *   1. 若 duration 变了 → PATCH /api/v1/studio/shot-details/{shot_id} { duration }
 *   2. POST /api/v1/film/tasks/video { shot_id, reference_mode, prompt, ratio, images:[] }
 *      （images 留空，后端 build_video_context 从 shot 帧图自动取，与 runner.ts 现状一致）
 * 「选具体参考图」(images 选择器) 留第三轮增量，本轮接口已预留（images 字段）。
 */
import { useEffect, useState } from 'react'
import { Modal, Form, InputNumber, Select, Input, Button, message, Spin } from 'antd'
import { FilmService } from '../../../../../../services/generated'
import { StudioShotDetailsService } from '../../../../../../services/generated'

// 各 reference_mode 需要的帧图槽位（与后端 REQUIRED_FRAMES_BY_MODE 一致）
const FRAMES_BY_MODE: Record<string, string[]> = {
  first: ['first'],
  last: ['last'],
  key: ['key'],
  first_last: ['first', 'last'],
  first_last_key: ['first', 'last', 'key'],
  text_only: [],
}

type FrameRow = { id: number; file_id: string | null; frame_type: string }

const REFERENCE_MODES = [
  { value: 'first', label: '首帧（first）' },
  { value: 'last', label: '尾帧（last）' },
  { value: 'key', label: '关键帧（key）' },
  { value: 'first_last', label: '首+尾（first_last）' },
  { value: 'first_last_key', label: '首+尾+关键（first_last_key）' },
  { value: 'text_only', label: '纯文本（text_only）' },
]

const RATIOS = [
  { value: '9:16', label: '9:16 竖屏' },
  { value: '16:9', label: '16:9 横屏' },
  { value: '4:3', label: '4:3' },
  { value: '1:1', label: '1:1 方形' },
  { value: '3:4', label: '3:4' },
  { value: '21:9', label: '21:9 宽屏' },
]

export type VideoEditModalProps = {
  open: boolean
  shotId: string | null
  /** 项目默认 ratio（从 project.default_video_ratio 读），作为表单初值 */
  projectRatio: string
  shotIndex?: number
  shotTitle?: string
  onClose: () => void
  /** 提交成功后回调（VideoStagePanel 刷新列表） */
  onSubmitted: () => void
}

type FormVals = {
  prompt: string
  duration: number
  reference_mode: 'first' | 'last' | 'key' | 'first_last' | 'first_last_key' | 'text_only'
  ratio: '16:9' | '4:3' | '1:1' | '3:4' | '9:16' | '21:9'
}

export function VideoEditModal({
  open, shotId, projectRatio, shotIndex, shotTitle, onClose, onSubmitted,
}: VideoEditModalProps) {
  const [form] = Form.useForm<FormVals>()
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  // 按 frame_type 分组的该 shot 帧图候选：{ first: [...], last: [...], key: [...] }
  const [frameImages, setFrameImages] = useState<Record<string, FrameRow[]>>({})
  // 各槽位选中的 file_id（槽位 = frame_type），未选则用后端自动
  const [selectedFrames, setSelectedFrames] = useState<Record<string, string | null>>({})
  const isTextOnly = Form.useWatch('reference_mode', form) === 'text_only'

  // 打开时拉 shot detail 拿当前 duration 作初值
  useEffect(() => {
    if (!open || !shotId) return
    setLoading(true)
    StudioShotDetailsService.getShotDetailApiV1StudioShotDetailsShotIdGet({ shotId })
      .then((res) => {
        const d = (res as any)?.data ?? res
        const dur = (d?.duration as number) ?? 8
        form.setFieldsValue({
          prompt: '',
          duration: dur,
          reference_mode: 'first',
          ratio: (projectRatio as any) || '9:16',
        })
      })
      .catch(() => {
        form.setFieldsValue({
          prompt: '', duration: 8, reference_mode: 'first',
          ratio: (projectRatio as any) || '9:16',
        })
      })
      .finally(() => setLoading(false))
    // 拉该 shot 的 first/last/key 三类帧图候选
    const fts = ['first', 'last', 'key']
    Promise.all(fts.map(async (ft) => {
      try {
          const r = await fetch(`/api/v1/studio/shot-frame-images?shot_detail_id=${shotId}&frame_type=${ft}&page_size=50`)
        const d = await r.json()
        const items: any[] = d?.data?.items ?? d?.items ?? []
        return [ft, items.map((it: any) => ({ id: it.id, file_id: it.file_id, frame_type: ft }))] as [string, FrameRow[]]
      } catch { return [ft, []] as [string, FrameRow[]] }
    })).then((rows) => {
      const map: Record<string, FrameRow[]> = {}
      rows.forEach(([ft, list]) => { map[ft] = list })
      setFrameImages(map)
    })
    setSelectedFrames({})
  }, [open, shotId, form, projectRatio])

  const handleSubmit = async () => {
    try {
      const vals = await form.validateFields()
      if (!shotId) { message.error('缺少镜头 ID'); return }
      if (isTextOnly && !vals.prompt?.trim()) {
        message.error('text_only 模式必须填提示词'); return
      }
      setSubmitting(true)
      // 1) 若 duration 变了，先 PATCH shot detail
      try {
        await StudioShotDetailsService.updateShotDetailApiV1StudioShotDetailsShotIdPatch({
          shotId,
          requestBody: { duration: vals.duration } as any,
        })
      } catch (e: any) {
        // duration 更新失败不阻断（可能未变更），继续提交任务
        console.warn('update shot detail failed', e)
      }
      // 2) 构造 images：按 reference_mode 需要的槽位顺序，取选中 file_id；未选则该槽位用后端自动（不传）
      const slots = FRAMES_BY_MODE[vals.reference_mode] || []
      const picked: string[] = []
      let allPicked = true
      for (const ft of slots) {
        const fid = selectedFrames[ft]
        if (fid) picked.push(fid)
        else { allPicked = false; break }
      }
      // 只有「每个槽位都选了」才传 images（覆盖后端自动）；否则传 [] 让后端自动取
      const images = allPicked ? picked : []
      const res: any = await FilmService.createVideoGenerationTaskApiV1FilmTasksVideoPost({
        requestBody: {
          shot_id: shotId,
          reference_mode: vals.reference_mode,
          prompt: vals.prompt?.trim() || null,
          images,
          ratio: vals.ratio,
        } as any,
      })
      const taskId = res?.data?.task_id ?? res?.data?.id
      if (taskId) {
        message.success(`已提交视频生成任务（任务 ${String(taskId).slice(0,8)}）`)
        onSubmitted()
        onClose()
      } else {
        message.error('任务未返回 task_id')
      }
    } catch (e: any) {
      // 校验失败或提交异常
      if (e?.errorFields) return // 表单校验，antd 已提示
      message.error(e?.message || '提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open={open}
      title={`编辑镜头视频参数${shotIndex ? ` · #${shotIndex}` : ''}${shotTitle ? ` ${shotTitle.slice(0,20)}` : ''}`}
      onCancel={onClose}
      width={560}
      destroyOnClose
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button key="ok" type="primary" loading={submitting} onClick={handleSubmit}>
          提交生成
        </Button>,
      ]}
    >
      <Spin spinning={loading} tip="加载镜头参数…">
      <Form form={form} layout="vertical" preserve={false} disabled={loading}>
          <Form.Item
            name="prompt"
            label="视频提示词"
            tooltip={isTextOnly ? 'text_only 模式必填' : '可选，作为补充描述；留空则用系统组装的提示词'}
            rules={isTextOnly ? [{ required: true, message: 'text_only 模式必填提示词' }] : []}
          >
            <Input.TextArea rows={4} placeholder="补充描述（可空，text_only 模式必填）" />
          </Form.Item>
          <Form.Item
            name="duration"
            label="时长（秒）"
            rules={[
              { required: true, message: '必填' },
              { type: 'number', min: 1, max: 30, message: '1-30 秒' },
            ]}
          >
            <InputNumber min={1} max={30} step={1} className="w-full" />
          </Form.Item>
          <Form.Item
            name="reference_mode"
            label="参考图模式"
            rules={[{ required: true }]}
            tooltip="选具体参考图（images 选择器）留第三轮增量"
          >
            <Select options={REFERENCE_MODES} />
          </Form.Item>
          <Form.Item
            name="ratio"
            label="画幅比例"
            rules={[{ required: true }]}
            tooltip={`项目默认 ${projectRatio}（从 project.default_video_ratio 读）`}
          >
            <Select options={RATIOS} />
          </Form.Item>
          <Form.Item label="参考图（可选）" tooltip="不选则用后端自动取该 shot 的最新帧图；选了则按槽位覆盖">
            <FramePicker
              slots={FRAMES_BY_MODE[form.getFieldValue('reference_mode') as string] || []}
              frameImages={frameImages}
              selectedFrames={selectedFrames}
              onChange={setSelectedFrames}
            />
          </Form.Item>
        </Form>
      </Spin>
    </Modal>
  )
}


/** 参考图选择器：按 reference_mode 需要的 frame_type 槽位展示，每槽单选一张帧图 */
function FramePicker({
  slots,
  frameImages,
  selectedFrames,
  onChange,
}: {
  slots: string[]
  frameImages: Record<string, FrameRow[]>
  selectedFrames: Record<string, string | null>
  onChange: (v: Record<string, string | null>) => void
}) {
  if (!slots.length) {
    return <div className="text-xs text-gray-400">text_only 模式不需要参考图</div>
  }
  const LABEL: Record<string, string> = { first: '首帧', last: '尾帧', key: '关键帧' }
  return (
    <div className="space-y-3">
      {slots.map((ft) => {
        const list: FrameRow[] = (frameImages[ft] ?? []) as FrameRow[]
        const sel = selectedFrames[ft] ?? null
        return (
          <div key={ft}>
            <div className="text-xs text-gray-500 mb-1">{LABEL[ft] || ft}（不选=后端自动）</div>
            {list.length === 0 ? (
              <div className="text-xs text-gray-400">该镜头无 {ft} 帧图，将用后端自动</div>
            ) : (
              <div className="flex gap-2 flex-wrap">
                {list.map((it) => {
                  const url = it.file_id ? `/api/v1/studio/files/${it.file_id}/download` : null
                  const active = sel === it.file_id
                  return (
                    <button
                      key={it.id}
                      type="button"
                      onClick={() => onChange({ ...selectedFrames, [ft]: active ? null : it.file_id })}
                      className={'relative w-[64px] h-[100px] rounded border-2 overflow-hidden bg-black ' + (active ? 'border-blue-500 ring-2 ring-blue-300' : 'border-gray-200 hover:border-blue-300')}
                      title={active ? '已选，点取消' : '点击选用'}
                    >
                      {url ? (
                        <img src={`${url}#t=0.1`} alt={ft} className="w-full h-full object-cover" />
                      ) : (
                        <span className="text-xs text-gray-400 flex items-center justify-center h-full">无图</span>
                      )}
                      {active && <span className="absolute top-0 right-0 bg-blue-500 text-white text-[10px] px-1">✓</span>}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}



