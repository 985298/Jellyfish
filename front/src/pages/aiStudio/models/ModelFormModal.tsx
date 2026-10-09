import { useEffect, useMemo } from 'react'
import { Modal, Form, Input, Select } from 'antd'
import { llmApi } from './llmApi'
import { genId } from './utils'
import { MODEL_CATEGORIES } from './constants'
import type { Model, Provider, SupportedProvider } from './types'

interface Props {
  open: boolean
  editing: Model | null
  providers: Provider[]
  supportedProviders: SupportedProvider[]
  presetCategory?: string
  onClose: () => void
  onSaved: () => void
}

export default function ModelFormModal({ open, editing, providers, supportedProviders, presetCategory, onClose, onSaved }: Props) {
  const [form] = Form.useForm()
  const selectedCategory = Form.useWatch('category', form)

  useEffect(() => {
    if (!open) return
    if (editing) {
      form.setFieldsValue({ name: editing.name, category: editing.category, provider_id: editing.provider_id, description: editing.description || '' })
    } else {
      form.resetFields()
      form.setFieldsValue({ category: presetCategory || 'text' })
    }
  }, [open, editing, form, presetCategory])

  const providerOptions = useMemo(() => {
    const cat = selectedCategory || presetCategory
    if (!cat) return providers.map(p => ({ label: p.name, value: p.id }))
    return providers.filter(p => {
      const spec = supportedProviders.find(s => s.display_name === p.name || s.aliases?.includes(p.name))
      return spec?.supported_categories?.includes(cat)
    }).map(p => ({ label: p.name, value: p.id }))
  }, [providers, selectedCategory, presetCategory, supportedProviders])

  const handleSave = async () => {
    try {
      const v = await form.validateFields()
      if (editing) {
        await llmApi.updateModel(editing.id, { name: v.name, category: v.category, provider_id: v.provider_id, description: v.description ?? null })
      } else {
        await llmApi.createModel({ id: genId('model'), name: v.name, category: v.category, provider_id: v.provider_id, description: v.description || '', params: {} })
      }
      onClose()
      onSaved()
    } catch (e: any) {
      if (e?.errorFields) return
    }
  }

  return (
    <Modal title={editing ? '编辑模型' : '添加模型'} open={open} onCancel={onClose} onOk={handleSave} width={480} destroyOnClose>
      <Form form={form} layout="vertical" className="pt-2">
        <Form.Item name="name" label="模型名称" rules={[{ required: true }]}><Input placeholder="gpt-4o / dall-e-3 / ..." /></Form.Item>
        <Form.Item name="category" label="类别" rules={[{ required: true }]}><Select options={MODEL_CATEGORIES.map(c => ({ label: c.label, value: c.key }))} /></Form.Item>
        <Form.Item name="provider_id" label="关联供应商" rules={[{ required: true, message: '请选择供应商' }]}>
          <Select placeholder={selectedCategory ? '选择支持该类别的供应商' : '选择供应商'} options={providerOptions} notFoundContent={selectedCategory ? '暂无支持该类别的供应商' : '暂无供应商'} />
        </Form.Item>
        <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
      </Form>
    </Modal>
  )
}
