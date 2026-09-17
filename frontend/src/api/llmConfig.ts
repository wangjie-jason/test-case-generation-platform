import client from './client'
import type { CredentialTestResult, LlmConfigForm, LlmConfigStatus } from '@/types/llmConfig'

export const llmConfigApi = {
  get() {
    return client.get<any, LlmConfigStatus>('/llm-config')
  },
  save(data: LlmConfigForm) {
    return client.put<any, LlmConfigStatus>('/llm-config', data)
  },
  clear() {
    return client.delete<any, { message: string }>('/llm-config')
  },
  // data 为空时测试当前已生效配置（个人或系统兜底）；否则按表单值先测后存。
  test(data?: Partial<LlmConfigForm>) {
    const hasValue = data && Object.values(data).some((v) => v && v.trim())
    return client.post<any, CredentialTestResult>('/llm-config/test', hasValue ? data : null)
  },
}
