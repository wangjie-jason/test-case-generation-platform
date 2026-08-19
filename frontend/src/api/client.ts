import axios from 'axios'
import type { AxiosResponse } from 'axios'

const client = axios.create({
  baseURL: '/api/v1',
  timeout: 60000,
})

// FastAPI 的 detail 有三种形态：业务异常抛的字符串、Pydantic 校验失败的数组
// （[{type, loc, msg, ...}]）、以及少数手写的对象。直接塞进 Error 会渲染成
// "[object Object]"，用户看不出哪个字段填错了，故按形态归一成可读文案。
function normalizeDetail(detail: unknown): string {
  if (detail == null) return ''
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      if (typeof item === 'string') return item
      const e = item as { loc?: unknown[]; msg?: string }
      // loc 形如 ["body", "requirement_text"]，末位才是字段名；msg 是原因。
      const field = Array.isArray(e.loc) && e.loc.length ? String(e.loc[e.loc.length - 1]) : ''
      const msg = e.msg || '格式不正确'
      return field ? `${field}：${msg}` : msg
    }).filter(Boolean).join('；')
  }
  return JSON.stringify(detail)
}

client.interceptors.response.use(
  (response: AxiosResponse) => {
    const data = response.data
    if (data.code !== undefined && data.code !== 0) {
      return Promise.reject(new Error(data.message || '请求失败'))
    }
    return data.data ?? data
  },
  (error) => {
    const message = normalizeDetail(error.response?.data?.detail) || error.message || '网络错误'
    return Promise.reject(new Error(message))
  }
)

export default client
