import type { Provider, Model, ModelSettings, ProbeResult, SupportedProvider } from './types'

// Token 由 vite proxy 注入，客户端不持有密钥
async function request(method: string, path: string, data?: unknown) {
  const opts: RequestInit = { method }
  if (data !== undefined) {
    opts.headers = { 'Content-Type': 'application/json' }
    opts.body = JSON.stringify(data)
  }
  const resp = await fetch(path, opts)
  if (!resp.ok) throw new Error('HTTP ' + resp.status)
  const body = await resp.json()
  return body?.data ?? body
}

export const llmApi = {
  listProviders: () => request('GET', '/api/v1/llm/providers?page=1&page_size=100'),
  getProvider: (id: string) => request('GET', '/api/v1/llm/providers/' + id),
  createProvider: (data: Partial<Provider> & { id: string; api_key?: string; api_secret?: string }) =>
    request('POST', '/api/v1/llm/providers', data),
  updateProvider: (id: string, data: Partial<Provider> & { api_key?: string; api_secret?: string }) =>
    request('PATCH', '/api/v1/llm/providers/' + id, data),
  deleteProvider: (id: string) => request('DELETE', '/api/v1/llm/providers/' + id),

  listModels: () => request('GET', '/api/v1/llm/models?page=1&page_size=100'),
  createModel: (data: Partial<Model> & { id: string }) => request('POST', '/api/v1/llm/models', data),
  updateModel: (id: string, data: Partial<Model>) => request('PATCH', '/api/v1/llm/models/' + id, data),
  deleteModel: (id: string) => request('DELETE', '/api/v1/llm/models/' + id),

  getModelSettings: () => request('GET', '/api/v1/llm/model-settings') as Promise<ModelSettings>,
  updateModelSettings: (data: Partial<ModelSettings>) => request('PUT', '/api/v1/llm/model-settings', data),

  listSupportedProviders: () => request('GET', '/api/v1/llm/providers/supported') as Promise<SupportedProvider[]>,
  probeProvider: (id: string) => request('POST', '/api/v1/llm/providers/' + id + '/probe') as Promise<ProbeResult>,
}
