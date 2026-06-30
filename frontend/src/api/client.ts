import axios from 'axios'
import type { AxiosResponse } from 'axios'

const client = axios.create({
  baseURL: '/api/v1',
  timeout: 60000,
})

client.interceptors.response.use(
  (response: AxiosResponse) => {
    const data = response.data
    if (data.code !== undefined && data.code !== 0) {
      return Promise.reject(new Error(data.message || '请求失败'))
    }
    return data.data ?? data
  },
  (error) => {
    const message = error.response?.data?.detail || error.message || '网络错误'
    return Promise.reject(new Error(message))
  }
)

export default client
