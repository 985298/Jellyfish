export function guessCategory(modelName: string): string {
  const n = (modelName || '').toLowerCase()
  if (/(super|upscale|2k|3k|4k|8k|超分)/.test(n)) return 'super_resolution'
  if (/(tts|speech|voice|语音|音频)/.test(n)) return 'tts'
  // i2v/图生视频 合并到 video
  if (/(sora|video|视频|i2v|image.to.video|图生视频|minimax|kling|hailuo|wan|cogvideo|pika|runway|gen-?[34]|animate|videocrafter|stable.video|vidu|luma|pixverse|hunyuan)/.test(n)) return 'video'
  if (/(dall|image|图片|stable|diffusion|seedream|绘图)/.test(n)) return 'image'
  return 'text'
}

export function genId(prefix: string): string {
  return prefix + '_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
}
