import { useEffect } from 'react'
import { Modal, Form, Input, Select } from 'antd'
import { llmApi } from './llmApi'
import { genId } from './utils'
import type { Provider, SupportedProvider } from './types'

interface Props {
  open: boolean
  editing: Provider | null
  supportedProviders: SupportedProvider[]
  onClose: () => void
  onSaved: () => void
}

export default function ProviderFormModal({ open, editing, supportedProviders, onClose, onSaved }: Props) {
  const [form] = Form.useForm()

  useEffect(() => {
    if (!open) return
    if (editing) {
      form.setFieldsValue({
        name: editing.name,
        base_url: editing.base_url,
        image_base_url: editing.image_base_url ?? null,
        video_base_url: editing.video_base_url ?? null,
        api_key: '********',
        api_secret: '********',
        description: editing.description,
        status: editing.status ?? 'active',
      })
    } else {
      form.resetFields()
      form.setFieldsValue({ status: 'active' })
    }
  }, [open, editing, form])

  const applyDefaultBaseUrl = (displayName: string) => {
    const spec = supportedProviders.find(s => s.display_name === displayName || s.aliases?.includes(displayName))
    const def = spec?.default_base_url?.trim()
    if (def && (!editing || !form.getFieldValue('base_url')?.trim())) {
      form.setFieldsValue({ base_url: def })
    }
  }

  const handleSave = async () => {
    try {
      const v = await form.validateFields()
      if (editing) {
        const body: Record<string, unknown> = {
          name: v.name, base_url: v.base_url,
          image_base_url: v.image_base_url ?? null,
          video_base_url: v.video_base_url ?? null,
          description: v.description ?? null,
          status: v.status ?? null,
        }
        if (v.api_key && v.api_key !== '********') body.api_key = v.api_key
        if (v.api_secret && v.api_secret !== '********') body.api_secret = v.api_secret
        await llmApi.updateProvider(editing.id, body)
      } else {
        await llmApi.createProvider({
          id: genId('prov'),
          name: v.name, base_url: v.base_url,
          image_base_url: v.image_base_url ?? null,
          video_base_url: v.video_base_url ?? null,
          description: v.description, status: v.status,
          api_key: v.api_key, api_secret: v.api_secret,
        })
      }
      onClose()
      onSaved()
    } catch (e: any) {
      if (e?.errorFields) return
    }
  }

  const nameOptions = supportedProviders.map(s => ({ label: s.display_name, value: s.display_name }))

  return (
    <Modal
      title={editing ? '编辑供应商' : '添加供应商'}
      open={open}
      onCancel={onClose}
      onOk={handleSave}
      width={560}
      destroyOnClose
    >
      <Form form={form} layout="vertical" className="pt-2">
        <Form.Item name="name" label="供应商" rules={[{ required: true }]}>
          <Select showSearch optionFilterProp="label" placeholder="选择供应商" options={nameOptions} onChange={(v) => applyDefaultBaseUrl(String(v))} />
        </Form.Item>
        <Form.Item name="base_url" label="Base URL" rules={[{ required: true }]}>
          <Input placeholder="https://api.openai.com/v1" />
        </Form.Item>
        <Form.Item name="image_base_url" label="图片 Base URL（可选）">
          <Input placeholder="留空回退到通用" />
        </Form.Item>
        <Form.Item name="video_base_url" label="视频 Base URL（可选）">
          <Input placeholder="留空回退到通用" />
        </Form.Item>
        <Form.Item name="api_key" label="API Key" help={editing ? '留空不修改' : ''}>
          <Input.Password placeholder="AK" />
        </Form.Item>
        <Form.Item name="api_secret" label="API Secret（可选）">
          <Input.Password placeholder="SK" />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item name="status" label="状态" initialValue="active">
          <Select options={[{ label: '活跃', value: 'active' }, { label: '测试中', value: 'testing' }, { label: '禁用', value: 'disabled' }]} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
