import axios, { AxiosInstance, AxiosRequestConfig, AxiosResponse } from 'axios'

const backendBaseUrl = import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:9123'
const baseURL = import.meta.env.VITE_API_BASE_URL ?? `${backendBaseUrl}/api`

const http: AxiosInstance = axios.create({
  baseURL,
  timeout: 10000,
})
// Token 由 vite proxy 注入，客户端不持有密钥

http.interceptors.response.use(
  (response: AxiosResponse) => {
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body && 'data' in body) {
      return body.data
    }
    return body
  },
  (error) => {
    return Promise.reject(error)
  },
)

// 响应拦截器已返回 response.data，此处声明为 Promise<T>
export const get = <T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> =>
  http.get<T>(url, config) as Promise<T>

export const post = <T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> =>
  http.post<T>(url, data, config) as Promise<T>

export const put = <T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> =>
  http.put<T>(url, data, config) as Promise<T>

export const del = <T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> =>
  http.delete<T>(url, config) as Promise<T>

export default http
