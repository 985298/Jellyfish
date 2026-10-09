import { useState, useEffect, useCallback } from 'react'
import { Tabs, Modal, message, Spin } from 'antd'
import { llmApi } from './llmApi'
import { guessCategory, genId } from './utils'
import ModelGridTab from './ModelGridTab'
import ProvidersTab from './ProvidersTab'
import ProviderFormModal from './ProviderFormModal'
import ModelFormModal from './ModelFormModal'
import type { Provider, Model, ModelSettings, SupportedProvider, ProbeModel } from './types'

export default function ModelManagement() {
  const [providers, setProviders] = useState<Provider[]>([])
  const [models, setModels] = useState<Model[]>([])
  const [settings, setSettings] = useState<ModelSettings>({})
  const [supportedProviders, setSupportedProviders] = useState<SupportedProvider[]>([])
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  // Probe state（从 ProvidersTab 上提）
  const [probing, setProbing] = useState<string | null>(null)
  const [probeResults, setProbeResults] = useState<Record<string, ProbeModel[]>>({})
  const [selectedModels, setSelectedModels] = useState<Record<string, string[]>>({})
  const [modelCategories, setModelCategories] = useState<Record<string, string>>({})

  // Modal state
  const [providerModalOpen, setProviderModalOpen] = useState(false)
  const [providerEditing, setProviderEditing] = useState<Provider | null>(null)
  const [modelModalOpen, setModelModalOpen] = useState(false)
  const [modelEditing, setModelEditing] = useState<Model | null>(null)
  const [presetCategory, setPresetCategory] = useState<string | undefined>(undefined)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [provRes, modelRes, settRes, suppRes] = await Promise.all([
        llmApi.listProviders(), llmApi.listModels(), llmApi.getModelSettings(), llmApi.listSupportedProviders(),
      ])
      setProviders(provRes?.items ?? [])
      setModels(modelRes?.items ?? [])
      setSettings(settRes ?? {})
      setSupportedProviders(suppRes ?? [])
    } catch (e) {
      message.error('加载失败: ' + (e instanceof Error ? e.message : String(e)))
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])

  const getDefaultId = (cat: string) => (settings as any)['default_' + cat + '_model_id']
  const getDefaultName = (cat: string) => models.find(m => m.id === getDefaultId(cat))?.name
  const providerModels = (pid: string) => models.filter(m => m.provider_id === pid)

  // ---- Model handlers ----
  const handleSetDefault = async (cat: string, mid: string) => {
    setActionLoading(mid)
    try {
      await llmApi.updateModelSettings({ ['default_' + cat + '_model_id']: mid } as any)
      message.success('已设为默认')
      void load()
    } catch { message.error('设置失败') }
    finally { setActionLoading(null) }
  }

  const handleDeleteModel = (m: Model) => {
    Modal.confirm({
      title: '删除模型',
      content: '确定删除「' + m.name + '」？',
      okText: '删除', okType: 'danger',
      onOk: async () => {
        setActionLoading(m.id)
        try { await llmApi.deleteModel(m.id); message.success('已删除'); void load() }
        catch { message.error('删除失败') }
        finally { setActionLoading(null) }
      },
    })
  }

  const handleDeleteProvider = (p: Provider) => {
    const linked = providerModels(p.id).length
    Modal.confirm({
      title: '删除供应商',
      content: linked > 0 ? '该供应商下还有 ' + linked + ' 个模型，删除后关联模型将失效。确定删除？' : '确定删除该供应商？',
      okText: '删除', okType: 'danger',
      onOk: async () => {
        setActionLoading(p.id)
        try {
          await llmApi.deleteProvider(p.id)
          // 清理探测状态
          setProbeResults(prev => { const n = { ...prev }; delete n[p.id]; return n })
          setSelectedModels(prev => { const n = { ...prev }; delete n[p.id]; return n })
          message.success('已删除'); void load()
        }
        catch { message.error('删除失败') }
        finally { setActionLoading(null) }
      },
    })
  }

  const openAddModel = (cat?: string) => { setModelEditing(null); setPresetCategory(cat); setModelModalOpen(true) }
  const openEditModel = (m: Model) => { setModelEditing(m); setPresetCategory(undefined); setModelModalOpen(true) }
  const openAddProvider = () => { setProviderEditing(null); setProviderModalOpen(true) }
  const openEditProvider = (p: Provider) => { setProviderEditing(p); setProviderModalOpen(true) }

  // ---- Probe handlers（从 ProvidersTab 上提）----
  const handleProbe = async (pid: string) => {
    setProbing(pid)
    try {
      const result = await llmApi.probeProvider(pid)
      const found: ProbeModel[] = result?.models ?? []
      setProbeResults(prev => ({ ...prev, [pid]: found }))
      const guessed: Record<string, string> = {}
      found.forEach(m => { guessed[m.id] = guessCategory(m.id) })
      setModelCategories(prev => ({ ...prev, ...guessed }))
      if (!found.length) message.warning('未发现可用模型')
      else message.success('发现 ' + found.length + ' 个模型，已自动识别类别')
    } catch (e: any) { message.error('探测失败: ' + (e?.message || '')) }
    finally { setProbing(null) }
  }

  const handleToggleModel = (pid: string, mid: string) => {
    setSelectedModels(prev => {
      const cur = prev[pid] ?? []
      return { ...prev, [pid]: cur.includes(mid) ? cur.filter(x => x !== mid) : [...cur, mid] }
    })
  }

  const handleCategoryChange = (mid: string, cat: string) => {
    setModelCategories(prev => ({ ...prev, [mid]: cat }))
  }

  const handleImport = async (pid: string) => {
    const selected = selectedModels[pid] ?? []
    if (!selected.length) { message.warning('请先勾选要导入的模型'); return }
    let success = 0
    const catNeedsDefault: Record<string, string> = {}
    for (const mid of selected) {
      const cat = modelCategories[mid] || 'text'
      try {
        const newId = genId(mid)
        await llmApi.createModel({ id: newId, name: mid, category: cat, provider_id: pid, params: {} })
        success++
        if (!getDefaultId(cat)) catNeedsDefault[cat] = newId
      } catch { message.error('导入 ' + mid + ' 失败') }
    }
    for (const [cat, mid] of Object.entries(catNeedsDefault)) {
      try { await llmApi.updateModelSettings({ ['default_' + cat + '_model_id']: mid } as any) } catch {}
    }
    if (success > 0) message.success('成功导入 ' + success + ' 个模型' + (Object.keys(catNeedsDefault).length ? '（已自动设默认）' : ''))
    setSelectedModels(prev => ({ ...prev, [pid]: [] }))
    void load()
  }

  const handleImportAll = async (pid: string) => {
    const probed = probeResults[pid] ?? []
    const existing = providerModels(pid)
    const newProbeModels = probed.filter(m => !existing.some(em => em.name === m.id))
    if (!newProbeModels.length) { message.warning('没有新模型可导入'); return }
    let success = 0
    const catNeedsDefault: Record<string, string> = {}
    for (const m of newProbeModels) {
      const cat = modelCategories[m.id] || guessCategory(m.id)
      try {
        const newId = genId(m.id)
        await llmApi.createModel({ id: newId, name: m.id, category: cat, provider_id: pid, params: {} })
        success++
        if (!getDefaultId(cat)) catNeedsDefault[cat] = newId
      } catch { message.error('导入 ' + m.id + ' 失败') }
    }
    for (const [cat, mid] of Object.entries(catNeedsDefault)) {
      try { await llmApi.updateModelSettings({ ['default_' + cat + '_model_id']: mid } as any) } catch {}
    }
    if (success > 0) message.success('成功导入 ' + success + ' 个模型' + (Object.keys(catNeedsDefault).length ? '（已自动设默认）' : ''))
    setSelectedModels(prev => ({ ...prev, [pid]: [] }))
    void load()
  }

  if (loading) return <div className="p-8 text-center"><Spin /></div>

  return (
    <div className="h-full flex flex-col">
      <div className="flex-shrink-0 px-4 py-3 border-b border-gray-200 bg-white">
        <span className="font-semibold text-gray-800">模型管理</span>
      </div>
      <div className="flex-1 min-h-0 overflow-hidden">
        <Tabs
          defaultActiveKey="models"
          className="px-4 pt-2"
          items={[
            {
              key: 'models',
              label: '模型列表 (' + models.length + ')',
              forceRender: true,
              children: (
                <ModelGridTab
                  models={models}
                  providers={providers}
                  getDefaultId={getDefaultId}
                  getDefaultName={getDefaultName}
                  onSetDefault={handleSetDefault}
                  onDeleteModel={handleDeleteModel}
                  onAddModel={openAddModel}
                  onEditModel={openEditModel}
                  actionLoading={actionLoading}
                />
              ),
            },
            {
              key: 'providers',
              label: '供应商 (' + providers.length + ')',
              forceRender: true,
              children: (
                <ProvidersTab
                  providers={providers}
                  models={models}
                  probing={probing}
                  probeResults={probeResults}
                  selectedModels={selectedModels}
                  modelCategories={modelCategories}
                  onAddProvider={openAddProvider}
                  onEditProvider={openEditProvider}
                  onDeleteProvider={handleDeleteProvider}
                  onProbe={handleProbe}
                  onToggleModel={handleToggleModel}
                 onCategoryChange={handleCategoryChange}
                  onImport={handleImport}
                  onImportAll={handleImportAll}
                />
              ),
            },
          ]}
        />
      </div>
      <ProviderFormModal
        open={providerModalOpen}
        editing={providerEditing}
        supportedProviders={supportedProviders}
        onClose={() => { setProviderModalOpen(false); setProviderEditing(null) }}
        onSaved={() => { setProviderModalOpen(false); setProviderEditing(null); void load() }}
      />
      <ModelFormModal
        open={modelModalOpen}
        editing={modelEditing}
        providers={providers}
        supportedProviders={supportedProviders}
        presetCategory={presetCategory}
        onClose={() => { setModelModalOpen(false); setModelEditing(null) }}
        onSaved={() => { setModelModalOpen(false); setModelEditing(null); void load() }}
      />
    </div>
  )
}
