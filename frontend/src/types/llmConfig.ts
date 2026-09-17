export interface LlmConfigStatus {
  // 是否配置了个人凭据
  configured: boolean
  base_url: string | null
  model: string | null
  api_key_masked: string | null
  updated_at: string | null
  // 系统兜底模型是否可用及其模型名
  fallback_available: boolean
  fallback_model: string | null
}

export interface LlmConfigForm {
  base_url: string
  // 空串表示不修改已保存的 key
  api_key?: string
  model: string
}

export interface CredentialTestResult {
  ok: boolean
  latency_ms: number | null
  message: string
}
