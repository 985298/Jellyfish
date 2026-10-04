import React, { useEffect, useState } from 'react'
import { Card, Button, Space, Dropdown, Empty } from 'antd'
import type { MenuProps } from 'antd'
import {
  PlusOutlined,
  EllipsisOutlined,
  ArrowLeftOutlined,
  VideoCameraFilled,
} from '@ant-design/icons'
import { Link, useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { TAB_CONFIG, TAB_GROUPS, type TabKey, isTabKey, DEFAULT_TAB } from './constants'
import { DashboardTab } from './tabs/DashboardTab'
import { ChaptersTab } from './tabs/ChaptersTab'
import { AllShotsTab } from './tabs/AllShotsTab'
import { ActorsTab } from './tabs/ActorsTab'
import { RolesTab } from './tabs/RolesTab'
import { ScenesTab } from './tabs/ScenesTab'
import { CostumesTab, PropsTab } from './tabs/PropsTab'
import { FilesTab } from './tabs/FilesTab'
import { EditTab } from './tabs/EditTab'
import { SettingsTab } from './tabs/SettingsTab'
import { getChapterShotsPath, getChapterStudioPath, getProjectEditorPath } from './routes'
import { useProject, useChapters } from './hooks/useProjectData'
import { ensureHasShotsBeforeShooting } from './ensureHasShotsBeforeShooting'
import { getChapterPreparationState } from './chapterPreparation'

const TAB_PARAM = 'tab'
const CREATE_PARAM = 'create'
const EDIT_PARAM = 'edit'

const ProjectWorkbench: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const tabFromUrl = searchParams.get(TAB_PARAM)
  const resolvedTab: TabKey =
    tabFromUrl !== null && isTabKey(tabFromUrl) ? tabFromUrl : DEFAULT_TAB

  const { project, loading: projectLoading } = useProject(projectId)
  const { chapters } = useChapters(projectId)
  const [activeTab, setActiveTab] = useState<TabKey>(() => resolvedTab)

  const chaptersByIndex = [...chapters].sort((a, b) => a.index - b.index)

  const recommendedChapter = (() => {
    const findByState = (key: ReturnType<typeof getChapterPreparationState>['key']) =>
      chaptersByIndex.find((chapter) => getChapterPreparationState(chapter).key === key)
    return (
      findByState('edit_raw') ??
      findByState('extract_shots') ??
      findByState('prepare_shots') ??
      findByState('shoot') ??
      chaptersByIndex[0] ??
      null
    )
  })()

  const primaryCta = (() => {
    if (!projectId) {
      return {
        label: '创建第一章',
        hint: '先创建章节，再进入分镜准备流程',
        icon: <PlusOutlined />,
        onClick: () => {},
      }
    }
    if (!recommendedChapter) {
      return {
        label: '创建第一章',
        hint: '先创建章节，再进入分镜准备流程',
        icon: <PlusOutlined />,
        onClick: () => {
          setTabInUrl('chapters')
          setSearchParams(
            (prev) => {
              const next = new URLSearchParams(prev)
              next.set(CREATE_PARAM, '1')
              return next
            },
            { replace: true }
          )
        },
      }
    }
    const state = getChapterPreparationState(recommendedChapter)
    const chapterLabel = `第${recommendedChapter.index}章`
    if (state.key === 'edit_raw') {
      return {
        label: `编辑${chapterLabel}原文`,
        hint: `${chapterLabel}还没有原文内容，建议先补章节原文`,
        icon: state.primaryIcon,
        onClick: () => {
          setTabInUrl('chapters')
          setSearchParams(
            (prev) => {
              const next = new URLSearchParams(prev)
              next.set(TAB_PARAM, 'chapters')
              next.set(EDIT_PARAM, recommendedChapter.id)
              return next
            },
            { replace: true }
          )
        },
      }
    }
    if (state.key === 'extract_shots') {
      return {
        label: `提取${chapterLabel}分镜`,
        hint: `${chapterLabel}已有原文，下一步更适合先提取分镜`,
        icon: state.primaryIcon,
        onClick: () => navigate(getChapterShotsPath(projectId, recommendedChapter.id)),
      }
    }
    if (state.key === 'prepare_shots') {
      return {
        label: `进入${chapterLabel}分镜工作室`,
        hint: `${chapterLabel}已有分镜，建议继续补齐镜头准备`,
        icon: state.primaryIcon,
        onClick: () => navigate(getChapterStudioPath(projectId, recommendedChapter.id)),
      }
    }
    return {
      label: `进入${chapterLabel}拍摄`,
      hint: `${chapterLabel}已具备分镜，可继续进入拍摄流程`,
      icon: state.primaryIcon,
      onClick: () =>
        ensureHasShotsBeforeShooting({
          projectId,
          chapterId: recommendedChapter.id,
          storyboardCount: recommendedChapter.storyboardCount,
          navigate,
        }),
    }
  })()

  // 与 URL 中的 tab 同步：URL 变化时更新 activeTab；初次或无效 tab 时写回 URL
  useEffect(() => {
    if (tabFromUrl !== null && isTabKey(tabFromUrl)) {
      setActiveTab(tabFromUrl)
    } else if (tabFromUrl === null || tabFromUrl === '') {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          next.set(TAB_PARAM, DEFAULT_TAB)
          return next
        },
        { replace: true }
      )
    }
  }, [tabFromUrl, setSearchParams])

  const setTabInUrl = (tab: TabKey) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set(TAB_PARAM, tab)
        return next
      },
      { replace: true }
    )
  }

  const moreMenuItems: MenuProps['items'] = [
    { key: 'newActor', label: '关联演员', onClick: () => setTabInUrl('actors') },
    { key: 'newRole', label: '新建角色', onClick: () => setTabInUrl('roles') },
    { key: 'upload', label: '上传素材', onClick: () => navigate(`/assets?projectId=${projectId}`) },
    { key: 'newScene', label: '新建场景', onClick: () => setTabInUrl('scenes') },
    { key: 'newProp', label: '新建道具', onClick: () => setTabInUrl('props') },
    { key: 'newCostume', label: '新建服装', onClick: () => setTabInUrl('costumes') },
  ]

  if (!project && !projectLoading) {
    return (
      <Card>
        <Empty description="项目不存在" />
        <Link to="/projects">
          <Button type="link" icon={<ArrowLeftOutlined />}>
            返回项目列表
          </Button>
        </Link>
      </Card>
    )
  }

  return (
    <div className="h-full min-h-0 flex">
      {/* 左侧 sidebar：章节速览 + 工具入口 */}
      <div className="w-56 shrink-0 border-r border-gray-200 bg-gray-50 flex flex-col overflow-y-auto">
        <div className="p-3 border-b border-gray-200">
          <Link to="/projects" className="text-sm text-gray-500 hover:text-gray-700 flex items-center gap-1">
            <ArrowLeftOutlined /> 返回项目列表
          </Link>
        </div>

        {/* 章节速览（点击进管线，不重复 ChaptersTab） */}
        <div className="p-3">
          <div className="text-xs text-gray-400 mb-2 uppercase tracking-wide">章节</div>
          {chaptersByIndex.length === 0 && (
            <div className="text-xs text-gray-400">暂无章节</div>
          )}
          {chaptersByIndex.slice(0, 8).map((ch) => {
            const st = getChapterPreparationState(ch)
            const stText = st.key === 'edit_raw' ? '待原文' : st.key === 'extract_shots' ? '待分镜' : st.key === 'prepare_shots' ? '准备中' : '可拍摄'
            return (
              <div
                key={ch.id}
                className={"px-2 py-1.5 rounded mb-1 text-xs cursor-pointer hover:bg-gray-200 flex items-center justify-between " + (recommendedChapter && ch.id === recommendedChapter.id ? "bg-blue-50 ring-1 ring-blue-200" : "")}
                onClick={() => projectId && navigate(getChapterStudioPath(projectId, ch.id))}
              >
                <span className="truncate flex-1 min-w-0">第{ch.index}章 {ch.title || ''}</span>
                <span className="text-gray-400 ml-1 shrink-0">{stText}</span>
              </div>
            )
          })}
          {chaptersByIndex.length > 8 && (
            <div className="text-xs text-gray-400 px-2 mt-1">+ {chaptersByIndex.length - 8} 更多（见章节管理）</div>
          )}
          <Button size="small" type="dashed" icon={<PlusOutlined />} className="w-full mt-2" onClick={() => setTabInUrl('chapters')}>
            新建章节
          </Button>
        </div>

        {/* 工具入口：TAB_GROUPS 转侧边菜单（功能不丢，从顶部平铺改侧边分组） */}
        <div className="p-3 border-t border-gray-200 flex-1">
          <div className="text-xs text-gray-400 mb-2 uppercase tracking-wide">工具</div>
          {TAB_GROUPS.map((group) => (
            <div key={group.label} className="mb-2">
              <div className="text-xs text-gray-400 px-2 mb-1">{group.label}</div>
              {group.keys.map((k) => {
                const cfg = TAB_CONFIG.find((t) => t.key === k)
                if (!cfg) return null
                return (
                  <div
                    key={k}
                    className={"px-2 py-1.5 rounded mb-0.5 text-sm cursor-pointer flex items-center gap-2 " + (activeTab === k ? "bg-blue-500 text-white" : "hover:bg-gray-200 text-gray-700")}
                    onClick={() => setTabInUrl(k)}
                  >
                    {cfg.icon}
                    <span>{cfg.label}</span>
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      </div>

      {/* 右侧 main：顶部 primaryCta 主进度 + 主体 activeTab 内容 */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* 顶部 sticky：醒目"继续制作"主按钮（复用现有 primaryCta 逻辑） */}
        <div className="sticky top-0 z-20 bg-white border-b border-gray-200 shadow-sm px-6 py-3">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-3 flex-1 min-w-0">
              <Button type="primary" size="large" icon={primaryCta.icon} onClick={primaryCta.onClick}>
                {primaryCta.label}
              </Button>
              <div className="text-xs text-gray-500 truncate">{primaryCta.hint}</div>
            </div>
            <Space size="small" wrap className="shrink-0">
              <Button icon={<VideoCameraFilled />} onClick={() => projectId && navigate(getProjectEditorPath(projectId))}>
                后期剪辑
              </Button>
              <Dropdown menu={{ items: moreMenuItems }} placement="bottomRight">
                <Button icon={<EllipsisOutlined />}>更多</Button>
              </Dropdown>
            </Space>
          </div>
        </div>

        {/* 主体：activeTab 内容组件（零改动，原样保留） */}
        <div className="pt-4 animate-fadeIn flex-1 min-h-0 overflow-y-auto px-6" style={{ animation: 'fadeIn 0.25s ease-out' }}>
          {activeTab === 'dashboard' && <DashboardTab onSelectTab={setTabInUrl} />}

          {activeTab === 'chapters' && <ChaptersTab />}

          {activeTab === 'all_shots' && <AllShotsTab />}
          {activeTab === 'actors' && <ActorsTab />}
          {activeTab === 'roles' && <RolesTab />}
          {activeTab === 'scenes' && <ScenesTab />}
          {activeTab === 'props' && <PropsTab />}
          {activeTab === 'costumes' && <CostumesTab />}
          {activeTab === 'files' && <FilesTab />}
          {activeTab === 'edit' && <EditTab />}
          {activeTab === 'settings' && <SettingsTab />}
        </div>
      </div>
    </div>
  )
}

export default ProjectWorkbench
