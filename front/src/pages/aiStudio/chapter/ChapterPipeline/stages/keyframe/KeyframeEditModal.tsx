/**
 * KeyframeEditModal — 帧图参数编辑表单（P0 补"单独编辑"要件）
 * 字段：frame_type（first/last/key）+ prompt
 * 提交：POST /api/v1/studio/image-tasks/shot/{shot_id}/frame-image-tasks
 *       { frame_type, prompt, target_ratio: '9:16' }
 */
import { useEffect, useState } from 'react'
import { Modal, Form, Select, Input, Button, message, Spin } from 'antd'

const FRAME_TYPES = [
  { value: 'first', label: '首帧（first）' },
  { value: 'last', label: '尾帧（last）' },
  { value: 'key', label: '关键帧（key）' },
]

export type KeyframeEditModalProps = {
  open: boolean
  shotId: string | null
  shotIndex?: number
  shotTitle?: string
  defaultPrompt?: string
  onClose: () => void
  onSubmitted: () => void
}

export function KeyframeEditModal({
  open, shotId, shotIndex, shotTitle, defaultPrompt, onClose, onSubmitted,
}: KeyframeEditModalProps) {
  const [form] = Form.useForm<{ frame_type: 'first'|'last'|'key'; prompt: string }>()
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    // 帧图参数无需额外拉取（prompt 默认用 script_excerpt），直接设初值
    form.setFieldsValue({
      frame_type: 'first',
      prompt: defaultPrompt || '',
    })
    setLoading(false)
  }, [open, shotId, form, defaultPrompt])

  const handleSubmit = async () => {
    try {
      const vals = await form.validateFields()
      if (!shotId) { message.error('缺少镜头 ID'); return }
      if (!vals.prompt?.trim()) { message.error('提示词必填'); return }
      setSubmitting(true)
      const r = await fetch(`/api/v1/studio/image-tasks/shot/${shotId}/frame-image-tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          frame_type: vals.frame_type,
          prompt: vals.prompt.trim(),
          target_ratio: '9:16',
          model_id: null,
        }),
      })
      const d = await r.json()
      const taskId = d?.data?.task_id ?? d?.data?.id
      if (taskId) {
        message.success(`已提交帧图生成任务（${String(taskId).slice(0,8)}）`)
        onSubmitted()
        onClose()
      } else {
        message.error(d?.message || '任务未返回 task_id')
      }
    } catch (e: any) {
      if (e?.errorFields) return
      message.error(e?.message || '提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open={open}
      title={`编辑帧图参数${shotIndex ? ` · #${shotIndex}` : ''}${shotTitle ? ` ${shotTitle.slice(0,20)}` : ''}`}
      onCancel={onClose}
      width={520}
      destroyOnClose
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button key="ok" type="primary" loading={submitting} onClick={handleSubmit}>提交生成</Button>,
      ]}
    >
      <Spin spinning={loading} tip="加载参数…">
        <Form form={form} layout="vertical" preserve={false} disabled={loading}>
          <Form.Item
            name="frame_type"
            label="帧类型"
            rules={[{ required: true }]}
            tooltip="first=首帧（默认），last=尾帧，key=关键帧"
          >
            <Select options={FRAME_TYPES} />
          </Form.Item>
          <Form.Item
            name="prompt"
            label="帧图提示词"
            rules={[{ required: true, message: '提示词必填' }]}
            tooltip="基于该提示词生成帧图；默认用镜头剧文兜底"
          >
            <Input.TextArea rows={5} placeholder="帧图提示词（默认用镜头剧文）" />
          </Form.Item>
        </Form>
      </Spin>
    </Modal>
  )
}
