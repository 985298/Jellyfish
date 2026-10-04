import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { message } from 'antd'
import { StudioChaptersService, StudioProjectsService, StudioShotsService } from '../../../services/generated'
import type { ShotRead } from '../../../services/generated'

// 章节级数据作用域（方案 C 第 1 轮）
// 目的：把 project / chapter / shots 这三个与「当前选中哪个镜头」无关的数据
// 提升到这里，使切换镜头时不再重复拉取，镜头列表也不再被整页 loading 替换。

export type ProjectVisualStyle = '现实' | '动漫'

type ChapterShotScopeValue = {
  projectId?: string
  chapterId?: string
  loading: boolean
  projectStyle: string
  projectVisualStyle: ProjectVisualStyle
  chapterTitle: string
  chapterIndex: number | null
  shots: ShotRead[]
  /** 用服务端返回的最新镜头对象更新列表中的一项 */
  patchShot: (next: ShotRead) => void
  refreshShots: () => Promise<void>
}

const ChapterShotScopeContext = createContext<ChapterShotScopeValue | null>(null)

const SHOTS_PAGE_SIZE = 100

export function ChapterShotScopeProvider({
  projectId,
  chapterId,
  children,
}: {
  projectId?: string
  chapterId?: string
  children: ReactNode
}) {
  const [loading, setLoading] = useState(true)
  const [projectStyle, setProjectStyle] = useState('真人都市')
  const [projectVisualStyle, setProjectVisualStyle] = useState<ProjectVisualStyle>('现实')
  const [chapterTitle, setChapterTitle] = useState('')
  const [chapterIndex, setChapterIndex] = useState<number | null>(null)
  const [shots, setShots] = useState<ShotRead[]>([])

  const load = useCallback(async () => {
    if (!projectId || !chapterId) return
    setLoading(true)
    try {
      const [projectRes, chRes, listRes] = await Promise.all([
        StudioProjectsService.getProjectApiV1StudioProjectsProjectIdGet({ projectId }),
        StudioChaptersService.getChapterApiV1StudioChaptersChapterIdGet({ chapterId }),
        StudioShotsService.listShotsApiV1StudioShotsGet({
          chapterId,
          page: 1,
          pageSize: SHOTS_PAGE_SIZE,
          order: 'index',
          isDesc: false,
        }),
      ])
      const nextVisualStyle = projectRes.data?.visual_style
      if (nextVisualStyle === '现实' || nextVisualStyle === '动漫') {
        setProjectVisualStyle(nextVisualStyle)
      }
      const nextStyle = projectRes.data?.style
      if (typeof nextStyle === 'string' && nextStyle.trim()) {
        setProjectStyle(nextStyle)
      }
      const c = chRes.data
      setChapterTitle(c?.title ?? '')
      setChapterIndex(typeof c?.index === 'number' ? c.index : null)
      setShots(listRes.data?.items ?? [])
    } catch {
      // 章节级数据拉取失败时不阻塞：镜头级加载会走到它自己的失败分支并跳回列表页
      message.error('章节信息加载失败')
    } finally {
      setLoading(false)
    }
  }, [chapterId, projectId])

  useEffect(() => {
    void load()
  }, [load])

  const patchShot = useCallback((next: ShotRead) => {
    setShots((prev) => prev.map((item) => (item.id === next.id ? next : item)))
  }, [])

  const refreshShots = useCallback(async () => {
    if (!chapterId) return
    const listRes = await StudioShotsService.listShotsApiV1StudioShotsGet({
      chapterId,
      page: 1,
      pageSize: SHOTS_PAGE_SIZE,
      order: 'index',
      isDesc: false,
    })
    setShots(listRes.data?.items ?? [])
  }, [chapterId])

  const value = useMemo<ChapterShotScopeValue>(
    () => ({
      projectId,
      chapterId,
      loading,
      projectStyle,
      projectVisualStyle,
      chapterTitle,
      chapterIndex,
      shots,
      patchShot,
      refreshShots,
    }),
    [
      chapterId,
      chapterIndex,
      chapterTitle,
      loading,
      patchShot,
      projectId,
      projectStyle,
      projectVisualStyle,
      refreshShots,
      shots,
    ],
  )

  return <ChapterShotScopeContext.Provider value={value}>{children}</ChapterShotScopeContext.Provider>
}

export function useChapterShotScope(): ChapterShotScopeValue {
  const ctx = useContext(ChapterShotScopeContext)
  if (!ctx) {
    throw new Error('useChapterShotScope 必须在 ChapterShotScopeProvider 内使用')
  }
  return ctx
}
