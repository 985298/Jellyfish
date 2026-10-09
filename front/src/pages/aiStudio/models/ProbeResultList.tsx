import { useMemo } from 'react'
import { Checkbox, Select, Button, Tag, Collapse } from 'antd'
import { CheckSquareOutlined } from '@ant-design/icons'
import { MODEL_CATEGORIES, categoryLabelMap, categoryColorMap } from './constants'
import { guessCategory } from './utils'
import type { ProbeModel, Model } from './types'

interface Props {
  models: ProbeModel[]
  existingModels: Model[]
  selected: string[]
  categories: Record<string, string>
  onToggle: (modelId: string) => void
  onCategoryChange: (modelId: string, category: string) => void
  onImport: () => void
  onImportAll?: () => void
}

export default function ProbeResultList({ models, existingModels, selected, categories, onToggle, onCategoryChange, onImport, onImportAll }: Props) {
  const isImported = (name: string) => existingModels.some(m => m.name === name)
  const newModels = models.filter(m => !isImported(m.id))

  const grouped = useMemo(() => {
    const groups: Record<string, ProbeModel[]> = {}
    for (const m of models) {
      const cat = categories[m.id] || guessCategory(m.id)
      if (!groups[cat]) groups[cat] = []
      groups[cat].push(m)
    }
    return groups
  }, [models, categories])

  if (!models.length) return null

  return (
    <div className="mt-3 border-t border-gray-100 pt-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-gray-500">
          探测到 {models.length} 个（{newModels.length} 新 / {models.length - newModels.length} 已导入）
        </span>
        <div className="flex gap-2">
          {newModels.length > 0 && onImportAll && (
            <Button size="small" icon={<CheckSquareOutlined />} onClick={onImportAll}>一键导入全部</Button>
          )}
          <Button type="primary" size="small" onClick={onImport} disabled={!selected.length}>
            导入选中({selected.length})
          </Button>
        </div>
      </div>
      <Collapse
        size="small"
        defaultActiveKey={Object.keys(grouped)}
        items={Object.entries(grouped).map(([cat, catModels]) => ({
          key: cat,
          label: (
            <div className="flex items-center gap-2">
              <Tag color={categoryColorMap[cat] || 'default'} className="m-0">{categoryLabelMap[cat] || cat}</Tag>
              <span className="text-xs text-gray-400">{catModels.length} 个</span>
            </div>
          ),
          children: (
            <div className="flex flex-wrap gap-1.5">
              {catModels.map(m => {
                const imported = isImported(m.id)
                return (
                  <div
                    key={m.id}
                    className="flex items-center gap-1.5 px-2 py-1 rounded"
                    style={{
                      border: '1px solid ' + (imported ? '#d9d9d9' : '#4096ff'),
                      background: imported ? '#fafafa' : '#f0f5ff',
                    }}
                  >
                    <Checkbox checked={selected.includes(m.id)} onChange={() => onToggle(m.id)} disabled={imported} />
                    <span className={imported ? 'text-gray-400 text-xs' : 'text-gray-700 text-xs'}>{m.id}</span>
                    {imported ? <Tag color="default" className="m-0">已导入</Tag> : <Tag color="blue" className="m-0">新</Tag>}
                    <Select
                      size="small"
                      value={categories[m.id] || guessCategory(m.id)}
                      onChange={(v: string) => onCategoryChange(m.id, v)}
                      options={MODEL_CATEGORIES.map(c => ({ label: c.label, value: c.key }))}
                      style={{ width: 90 }}
                    />
                  </div>
                )
              })}
            </div>
          ),
        }))}
      />
    </div>
  )
}
