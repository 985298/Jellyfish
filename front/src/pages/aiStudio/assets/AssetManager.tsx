import { useEffect, useMemo, useState } from 'react'
import { Card, Select, Space, Tag, Tabs } from 'antd'
import { ProjectOutlined } from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import { StudioProjectsService } from '../../../services/generated'
import type { ProjectRead } from '../../../services/generated'
import { ActorsTab } from './tabs/ActorsTab'
import { ScenesTab } from './tabs/ScenesTab'
import { PropsTab } from './tabs/PropsTab'
import { CostumesTab } from './tabs/CostumesTab'

const TAB_PARAM = 'tab'
const PROJECT_PARAM = 'projectId'
type AssetTabKey = 'actor' | 'scene' | 'prop' | 'costume'

function isValidTab(tab: string | null): tab is AssetTabKey {
  return tab === 'actor' || tab === 'scene' || tab === 'prop' || tab === 'costume'
}

const AssetManager = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const tabFromUrl = searchParams.get(TAB_PARAM)
  const projectFromUrl = searchParams.get(PROJECT_PARAM)?.trim() ?? ''

  const [activeTab, setActiveTab] = useState<AssetTabKey>(() => (isValidTab(tabFromUrl) ? tabFromUrl : 'actor'))

  // 项目选择器数据
  const [projects, setProjects] = useState<ProjectRead[]>([])
  const [projectsLoading, setProjectsLoading] = useState(false)
  const [selectedProjectId, setSelectedProjectId] = useState<string>(() => projectFromUrl)

  useEffect(() => {
    if (isValidTab(tabFromUrl)) {
      setActiveTab(tabFromUrl)
    } else if (tabFromUrl === null || tabFromUrl === '') {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          next.set(TAB_PARAM, 'actor')
          return next
        },
        { replace: true },
      )
    }
  }, [tabFromUrl, setSearchParams])

  // 加载项目列表供选择器使用
  useEffect(() => {
    let cancelled = false
    const loadProjects = async () => {
      setProjectsLoading(true)
      try {
        const res = await StudioProjectsService.listProjectsApiV1StudioProjectsGet({
          page: 1,
          pageSize: 100,
        })
        if (cancelled) return
        setProjects(res.data?.items ?? [])
      } catch {
        if (!cancelled) setProjects([])
      } finally {
        if (!cancelled) setProjectsLoading(false)
      }
    }
    void loadProjects()
    return () => {
      cancelled = true
    }
  }, [])

  // URL 携带 projectId 时同步到选择器（支持从项目工作台跳转过来时预选项目）。
  // 仅在 URL 提供非空 projectId 时同步，避免 shot 内新建流程清理 URL 参数时
  // 误清空选择器（保留用户已选项目）。
  useEffect(() => {
    if (projectFromUrl) setSelectedProjectId(projectFromUrl)
  }, [projectFromUrl])

  const setTabInUrl = (tab: AssetTabKey) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set(TAB_PARAM, tab)
        return next
      },
      { replace: true },
    )
  }

  const handleProjectChange = (value: string | undefined) => {
    const next = value ?? ''
    setSelectedProjectId(next)
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev)
        if (next) {
          params.set(PROJECT_PARAM, next)
        } else {
          params.delete(PROJECT_PARAM)
        }
        return params
      },
      { replace: true },
    )
  }

  const projectOptions = useMemo(() => {
    const opts = projects.map((p) => ({ value: p.id, label: p.name }))
    // 若当前选中项目不在已加载列表中，补一条占位，避免 Select 显示空值
    if (selectedProjectId && !projects.some((p) => p.id === selectedProjectId)) {
      opts.unshift({ value: selectedProjectId, label: selectedProjectId })
    }
    return opts
  }, [projects, selectedProjectId])

  const selectedProject = projects.find((p) => p.id === selectedProjectId)

  return (
    <div className="space-y-4 h-full overflow-auto">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
          <Space size="middle" wrap>
            <Space size="small" align="center">
              <ProjectOutlined className="text-gray-500" />
              <span className="text-sm text-gray-600">项目：</span>
              <Select
                style={{ minWidth: 240 }}
                allowClear
                showSearch
                placeholder="选择项目以过滤资产（留空查看全部）"
                loading={projectsLoading}
                value={selectedProjectId || undefined}
                onChange={handleProjectChange}
                options={projectOptions}
                optionFilterProp="label"
              />
              {selectedProject ? (
                <Tag color="blue" className="m-0">
                  {selectedProject.name}
                </Tag>
              ) : null}
            </Space>
          </Space>
        </div>
        <Tabs
          activeKey={activeTab}
          onChange={(k) => {
            if (isValidTab(k)) setTabInUrl(k)
          }}
          items={[
            { key: 'actor', label: '演员', children: <ActorsTab projectId={selectedProjectId} /> },
            { key: 'scene', label: '场景', children: <ScenesTab projectId={selectedProjectId} /> },
            { key: 'prop', label: '道具', children: <PropsTab projectId={selectedProjectId} /> },
            { key: 'costume', label: '服装', children: <CostumesTab projectId={selectedProjectId} /> },
          ]}
        />
      </Card>
    </div>
  )
}

export default AssetManager
