export interface Provider {
  id: string
  name: string
  base_url: string
  image_base_url?: string | null
  video_base_url?: string | null
  description?: string
  status: string
  created_by?: string
}

export interface Model {
  id: string
  name: string
  category: string
  provider_id: string
  params?: Record<string, unknown>
  description?: string
  created_by?: string
}

export interface ModelSettings {
  id?: number
  default_text_model_id?: string | null
  default_image_model_id?: string | null
  default_video_model_id?: string | null
  default_image_to_video_model_id?: string | null
  default_super_resolution_model_id?: string | null
  default_tts_model_id?: string | null
  api_timeout?: number
  log_level?: string
}

export interface ProbeModel {
  id: string
  name?: string
  raw?: Record<string, unknown>
}

export interface ProbeResult {
  provider_id: string
  models: ProbeModel[]
  raw_status?: number | null
}

export interface SupportedProvider {
  key: string
  display_name: string
  aliases?: string[]
  supported_categories: string[]
  default_base_url?: string | null
  requires_api_key: boolean
  requires_api_secret: boolean
  is_experimental: boolean
}
