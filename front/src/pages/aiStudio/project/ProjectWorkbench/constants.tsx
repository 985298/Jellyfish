import React from 'react'
import {
  HomeOutlined,
  UnorderedListOutlined,
  UserOutlined,
  PictureOutlined,
  ScissorOutlined,
  FileImageOutlined,
  VideoCameraOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import type { Chapter } from '../../../../mocks/data'

export type TabKey =
  | 'dashboard'
  | 'chapters'
  | 'all_shots'
  | 'actors'
  | 'roles'
  | 'scenes'
  | 'props'
  | 'costumes'
  | 'files'
  | 'edit'
  | 'settings'

const TAB_KEYS: TabKey[] = [
  'dashboard',
  'chapters',
  'all_shots',
  'actors',
  'roles',
  'scenes',
  'props',
  'costumes',
  'files',
  'edit',
  'settings',
]

export function isTabKey(s: string): s is TabKey {
  return TAB_KEYS.includes(s as TabKey)
}

export const DEFAULT_TAB: TabKey = 'dashboard'

export const TAB_CONFIG: { key: TabKey; label: string; icon: React.ReactNode }[] = [
  { key: 'dashboard', label: '仪表盘', icon: <HomeOutlined /> },
  { key: 'chapters', label: '章节', icon: <UnorderedListOutlined /> },
  { key: 'all_shots', label: '全部分镜', icon: <PictureOutlined /> },
  { key: 'actors', label: '演员', icon: <UserOutlined /> },
  { key: 'roles', label: '角色', icon: <UserOutlined /> },
  { key: 'scenes', label: '场景', icon: <PictureOutlined /> },
  { key: 'props', label: '道具', icon: <ScissorOutlined /> },
  { key: 'costumes', label: '服装', icon: <ScissorOutlined /> },
  { key: 'files', label: '文件', icon: <FileImageOutlined /> },
  { key: 'edit', label: '剪辑', icon: <VideoCameraOutlined /> },
  { key: 'settings', label: '设置', icon: <SettingOutlined /> },
]

export const chapterStatusMap: Record<Chapter['status'], { color: string; text: string }> = {
  draft: { color: 'default', text: '草稿' },
  shooting: { color: 'processing', text: '拍摄中' },
  partial: { color: 'warning', text: '部分完成' },
  done: { color: 'success', text: '完成' },
}

export type TabGroup = {
  label: string
  keys: TabKey[]
}

export const TAB_GROUPS: TabGroup[] = [
  { label: '总览', keys: ['dashboard', 'chapters', 'all_shots'] },
  { label: '资产', keys: ['actors', 'roles', 'scenes', 'props', 'costumes', 'files'] },
  { label: '后期', keys: ['edit'] },
  { label: '其他', keys: ['settings'] },
]

