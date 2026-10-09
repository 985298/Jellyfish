
export const MODEL_CATEGORIES: { key: string; label: string; color: string }[] = [
  { key: 'text', label: '文本生成', color: 'blue' },
  { key: 'image', label: '图片生成', color: 'orange' },
  { key: 'video', label: '视频生成', color: 'purple' },
  { key: 'super_resolution', label: '超分辨率', color: 'green' },
  { key: 'tts', label: '语音合成', color: 'magenta' },
]

export const categoryLabelMap = Object.fromEntries(MODEL_CATEGORIES.map((c) => [c.key, c.label]))
export const categoryColorMap = Object.fromEntries(MODEL_CATEGORIES.map((c) => [c.key, c.color]))

export const PROVIDER_STATUS_MAP: Record<string, { text: string; color: string }> = {
  active: { text: '活跃', color: 'green' },
  testing: { text: '测试中', color: 'orange' },
  disabled: { text: '禁用', color: 'default' },
}
