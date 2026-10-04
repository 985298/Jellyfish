import React, { useMemo, useEffect, useState, useCallback } from 'react'
import { Layout, Menu, theme, Dropdown, Space, Avatar, Select, Breadcrumb, Modal, Input, Spin, Empty, Tooltip } from 'antd'
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SettingOutlined,
  UserOutlined,
  FolderOutlined,
  PictureOutlined,
  FileTextOutlined,
  ApiOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAppStore } from '../store/useAppStore'
import { useTranslation } from 'react-i18next'
import { TaskCenter } from '../pages/aiStudio/components/TaskCenter'
import { TaskRuntimeProvider } from '../pages/aiStudio/components/TaskRuntimeProvider'
import { StudioProjectsService, StudioChaptersService, StudioEntitiesService } from '../services/generated'

const { Header, Sider, Content } = Layout

// U15：面包屑章节段标签——异步查章节 index，显示"第 N 章"
function ChapterBreadcrumbLabel({ chapterId }: { chapterId: string }) {
  const [label, setLabel] = useState<string>('章节')
  useEffect(() => {
    let cancelled = false
    void StudioChaptersService.getChapterApiV1StudioChaptersChapterIdGet({ chapterId })
      .then((res) => {
        if (cancelled) return
        const ch = res.data
        if (ch && typeof ch.index === 'number') {
          setLabel(`第${ch.index}章`)
        }
      })
      .catch(() => { /* 回退到"章节" */ })
    return () => { cancelled = true }
  }, [chapterId])
  return <>{label}</>
}

const MainLayout: React.FC = () => {
  const { t, i18n } = useTranslation('layout')
  const location = useLocation()
  const navigate = useNavigate()
  const { token } = theme.useToken()

  const collapsed = useAppStore((state) => state.siderCollapsed)
  const toggleCollapsed = useAppStore((state) => state.toggleSider)
  const user = useAppStore((state) => state.user)
  const language = useAppStore((state) => state.language)
  const setLanguage = useAppStore((state) => state.setLanguage)

  const selectedKeys = useMemo(() => {
    if (location.pathname === '/projects' || location.pathname.startsWith('/projects/')) return ['projects']
    if (location.pathname.startsWith('/assets')) return ['assets']
    if (location.pathname.startsWith('/prompts')) return ['prompts']
    if (location.pathname.startsWith('/files')) return ['files']
    if (location.pathname.startsWith('/agents')) return ['agents']
    if (location.pathname.startsWith('/models')) return ['models']
    if (location.pathname.startsWith('/settings')) return ['settings']
    return []
  }, [location.pathname])

  const breadcrumbItems = useMemo(() => {
    const path = location.pathname.replace(/^\/+/, '').split('/').filter(Boolean)
    if (path.length === 0) return [{ title: t('title') }]
    const items: { title: React.ReactNode; key: string }[] = []
    const pathLabels: Record<string, string> = {
      projects: '项目列表',
      assets: '资产管理',
      prompts: '提示词模板',
      files: '文件管理',
      agents: 'Agent管理',
      models: '模型管理',
      settings: t('menu.settings'),
      chapters: '章节管理',
      studio: '分镜工作室',
      prep: '章节编辑',
      shots: '分镜',
      editor: '视频剪辑',
      edit: '编辑',
    }
    path.forEach((segment, i) => {
      // U15：chapterId 段映射为"第 N 章"（查章节 index），不再省略
      if (path[0] === 'projects' && path[2] === 'chapters' && i === 3) {
        const projectId = path[1]
        const chapterId = path[3]
        const href = `/projects/${projectId}/chapters/${chapterId}/shots`
        const isLast = i === path.length - 1
        // 章节序号异步解析失败时回退到"章节"，避免阻塞面包屑渲染
        items.push({
          key: `chapter-${chapterId}`,
          title: isLast ? <ChapterBreadcrumbLabel chapterId={chapterId} /> : <Link to={href}><ChapterBreadcrumbLabel chapterId={chapterId} /></Link>,
        })
        return
      }

      // 默认：按原始路径逐段拼接
      let href = path.slice(0, i + 1).join('/')
      href = `/${href}`

      // 特殊：章节相关的中间路径段在路由里不存在，需映射到有效地址
      // /projects/:projectId/chapters/:chapterId/*
      if (path[0] === 'projects' && path[2] === 'chapters') {
        const projectId = path[1]
        if (segment === 'chapters' && i === 2) {
          // “章节管理”实际在项目工作台页
          href = `/projects/${projectId}?tab=chapters`
        }
      }

      const isLast = i === path.length - 1
      let label = pathLabels[segment]
      if (label === undefined) {
        if (path[0] === 'projects' && i === 1) label = '项目工作台'
        else label = segment
      }
      items.push({
        key: href,
        title: isLast ? label : <Link to={href}>{label}</Link>,
      })
    })
    return items
  }, [location.pathname, t])

  const menuItems = [
    {
      key: 'projects',
      icon: <FolderOutlined />,
      label: <Link to="/projects">项目列表</Link>,
    },
    {
      key: 'assets',
      icon: <PictureOutlined />,
      label: <Link to="/assets">资产管理</Link>,
    },
    {
      key: 'prompts',
      icon: <FileTextOutlined />,
      label: <Link to="/prompts">提示词模板</Link>,
    },
    {
      key: 'models',
      icon: <ApiOutlined />,
      label: <Link to="/models">模型管理</Link>,
    },
    {
      key: 'settings',
      icon: <SettingOutlined />,
      label: <Link to="/settings">{t('menu.settings')}</Link>,
    },
  ]

  const userMenuItems = [
    {
      key: 'profile',
      label: t('user.profile'),
      onClick: () => navigate('/settings'),
    },
    {
      type: 'divider' as const,
    },
    {
      key: 'logout',
      label: t('user.logout'),
      onClick: () => {
        // 这里保留占位，实际项目中可接入登录逻辑
      },
    },
  ]

  // U11：全局搜索（Cmd+K / Ctrl+K）
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchResults, setSearchResults] = useState<Array<{ kind: 'project' | 'chapter' | 'shot' | 'asset'; id: string; title: string; subtitle?: string; href: string }>>([])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setSearchOpen(true)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const runSearch = useCallback(async (q: string) => {
    const trimmed = q.trim()
    if (!trimmed) {
      setSearchResults([])
      return
    }
    setSearchLoading(true)
    try {
      const [projRes, chRes, charRes] = await Promise.all([
        StudioProjectsService.listProjectsApiV1StudioProjectsGet({ q: trimmed, page: 1, pageSize: 5 }).catch(() => null),
        StudioChaptersService.listChaptersApiV1StudioChaptersGet({ q: trimmed, page: 1, pageSize: 5 }).catch(() => null),
        StudioEntitiesService.listEntitiesApiV1StudioEntitiesEntityTypeGet({ entityType: 'character', q: trimmed, page: 1, pageSize: 5 }).catch(() => null),
      ])
      const results: Array<{ kind: 'project' | 'chapter' | 'shot' | 'asset'; id: string; title: string; subtitle?: string; href: string }> = []
      const projects = (projRes?.data?.items ?? []) as Array<{ id: string; name?: string }>
      projects.forEach((p) => {
        results.push({ kind: 'project', id: p.id, title: p.name || '未命名项目', subtitle: '项目', href: `/projects/${p.id}` })
      })
      const chapters = (chRes?.data?.items ?? []) as Array<{ id: string; title?: string; index?: number; project_id?: string }>
      chapters.forEach((c) => {
        results.push({
          kind: 'chapter',
          id: c.id,
          title: `第${c.index ?? '?'}章 · ${c.title || '未命名'}`,
          subtitle: '章节',
          href: `/projects/${c.project_id}/chapters/${c.id}/shots`,
        })
      })
      const chars = (charRes?.data?.items ?? []) as Array<{ id: string; name?: string; project_id?: string }>
      chars.forEach((c) => {
        results.push({
          kind: 'asset',
          id: c.id,
          title: c.name || '未命名角色',
          subtitle: '角色',
          href: `/projects/${c.project_id}?tab=roles`,
        })
      })
      setSearchResults(results)
    } catch {
      setSearchResults([])
    } finally {
      setSearchLoading(false)
    }
  }, [])

  useEffect(() => {
    const t = setTimeout(() => void runSearch(searchQuery), 300)
    return () => clearTimeout(t)
  }, [searchQuery, runSearch])

  return (
    <Layout
      style={{
        height: '100vh',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'row',
      }}
    >
      <Sider
        trigger={null}
        collapsible
        collapsed={collapsed}
        width={220}
        style={{
          flexShrink: 0,
          background: token.colorBgContainer,
          borderRight: `1px solid ${token.colorBorderSecondary}`,
          overflow: 'auto',
        }}
      >
        <div className="flex items-center h-16 px-4 border-b border-solid" style={{ borderColor: token.colorBorderSecondary }}>
          <Link to="/projects" className="flex items-center gap-2 min-w-0">
            <img src="/logo.svg" alt="Jellyfish" className="w-8 h-8 shrink-0" />
            {!collapsed && (
              <div className="min-w-0">
                <div className="text-base font-semibold text-gray-900 truncate">
                  {t('title')}
                </div>
                <div className="text-xs text-gray-500 truncate">
                  {t('subtitle')}
                </div>
              </div>
            )}
          </Link>
        </div>

        <Menu
          mode="inline"
          selectedKeys={selectedKeys}
          items={menuItems}
          style={{ borderRight: 'none', paddingTop: 8 }}
        />
      </Sider>

      <Layout
        style={{
          flex: 1,
          minWidth: 0,
          display: 'flex',
          flexDirection: 'column',
          minHeight: 0,
        }}
      >
        <Header
          className="flex items-center justify-between px-4"
          style={{
            flexShrink: 0,
            background: token.colorBgContainer,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
          <Space size="middle" className="flex-1 min-w-0">
            <span
              className="cursor-pointer text-xl shrink-0"
              onClick={toggleCollapsed}
            >
              {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            </span>
            <Breadcrumb
              items={breadcrumbItems}
              className="hidden sm:block"
              style={{ lineHeight: '32px' }}
            />
          </Space>

          <Space size="middle">
            <Tooltip title="全局搜索 (Cmd+K)">
              <span
                className="cursor-pointer text-xl shrink-0"
                onClick={() => setSearchOpen(true)}
              >
                <SearchOutlined />
              </span>
            </Tooltip>
            <Select
              size="small"
              value={language}
              style={{ width: 120 }}
              onChange={(value) => {
                setLanguage(value)
                void i18n.changeLanguage(value)
                window.localStorage.setItem('jellyfish_language', value)
                document.documentElement.lang = value === 'en-US' ? 'en' : 'zh-CN'
              }}
              options={[
                { label: t('lang.zh'), value: 'zh-CN' },
                { label: t('lang.en'), value: 'en-US' },
              ]}
            />

            <Dropdown
              menu={{
                items: userMenuItems,
              }}
              placement="bottomRight"
            >
              <div className="flex items-center gap-2 cursor-pointer">
                <Avatar size={32} icon={<UserOutlined />} />
                <div className="hidden md:flex flex-col leading-tight">
                  <span className="text-sm font-medium text-gray-800">{user.name}</span>
                  <span className="text-xs text-gray-500">{user.role}</span>
                </div>
              </div>
            </Dropdown>
          </Space>
        </Header>

        <TaskRuntimeProvider>
          <Content
            style={{
              margin: 0,
              padding: 5,
              background: token.colorBgLayout,
              flex: 1,
              minHeight: 0,
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <div className="w-full h-full min-h-0 overflow-hidden flex flex-col">
              <Outlet />
            </div>
          </Content>
          <TaskCenter />
        </TaskRuntimeProvider>
      </Layout>

      <Modal
        title="全局搜索"
        open={searchOpen}
        onCancel={() => { setSearchOpen(false); setSearchQuery('') }}
        footer={null}
        width={560}
      >
        <Input
          autoFocus
          placeholder="搜索项目 / 章节 / 角色... (Cmd+K 唤起)"
          prefix={<SearchOutlined />}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          allowClear
        />
        <div className="mt-3 max-h-96 overflow-y-auto">
          {searchLoading ? (
            <div className="flex justify-center py-8"><Spin tip="搜索中..." /></div>
          ) : searchResults.length === 0 ? (
            <Empty description={searchQuery ? '无匹配结果' : '输入关键字搜索项目/章节/角色'} image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <div className="space-y-1">
              {searchResults.map((r) => (
                <div
                  key={`${r.kind}-${r.id}`}
                  className="p-2 rounded hover:bg-blue-50 cursor-pointer flex items-center justify-between"
                  onClick={() => {
                    navigate(r.href)
                    setSearchOpen(false)
                    setSearchQuery('')
                  }}
                >
                  <div className="min-w-0">
                    <div className="text-sm truncate">{r.title}</div>
                    <div className="text-xs text-gray-400">{r.subtitle}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </Modal>
    </Layout>
  )
}

export default MainLayout
