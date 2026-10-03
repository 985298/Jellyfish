export function getProjectChaptersPath(projectId: string) {
  return `/projects/${projectId}/chapters`
}

export function getChapterStudioPath(projectId: string, chapterId: string) {
  // 历史命名：函数名为 Studio 但实际指向分镜列表页（老 Studio 页已废弃）。
  // 保留函数名以避免 11 处调用方改动，新代码请直接用 getChapterShotsPath。
  return `/projects/${projectId}/chapters/${chapterId}/shots`
}

export function getChapterShotsPath(projectId: string, chapterId: string) {
  return `/projects/${projectId}/chapters/${chapterId}/shots`
}

export function getChapterShotEditPath(projectId: string, chapterId: string, shotId: string) {
  return `/projects/${projectId}/chapters/${chapterId}/shots/${shotId}/edit`
}

export function getProjectEditorPath(projectId: string) {
  return `/projects/${projectId}/editor`
}

