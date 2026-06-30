import client from './client'
import type { GeneratedTestCase, TestCase } from '@/types/testCase'

export interface GenerateRequest {
  kb_ids: string[]
  requirement_text: string
  batch_name?: string
}

export interface KnowledgeMatches {
  field_dicts?: Array<Record<string, unknown>>
  business_rules?: Array<Record<string, unknown>>
  state_machines?: Array<Record<string, unknown>>
  term_mappings?: Array<Record<string, unknown>>
  prd_chunks?: Array<Record<string, unknown>>
  defect_chunks?: Array<Record<string, unknown>>
  historical_cases?: Array<Record<string, unknown>>
}

export interface GenerateResponse {
  cases: GeneratedTestCase[]
  knowledge_used: Record<string, number>
  knowledge_matches: KnowledgeMatches
  validation_warnings: unknown[] | null
}

export interface ParsedPrd {
  filename: string
  format: string
  text: string
  length: number
}

export type GenerateStreamEvent =
  | { type: 'progress'; stage: string; message: string }
  | { type: 'chunk'; text: string }
  | {
      type: 'complete'
      cases: GeneratedTestCase[]
      knowledge_used: Record<string, number>
      knowledge_matches: KnowledgeMatches
      validation_warnings: unknown[] | null
    }
  | { type: 'error'; message: string }

export interface CaseRecord extends TestCase {
  batch_id?: string | null
  req_text?: string | null
  created_at?: string
  review?: {
    status: 'approved' | 'rejected'
    reject_reason?: string | null
  } | null
}

export interface StatsOverview {
  total_cases: number
  reviewed_cases: number
  approved_cases: number
  rejected_cases: number
  usability_rate: number
  hallucination_distribution: Record<string, number>
  generation_count: number
}

export const generationApi = {
  generate(data: GenerateRequest) { return client.post<any, GenerateResponse>('/generate', data) },
  async generateStream(data: GenerateRequest, onEvent: (event: GenerateStreamEvent) => void): Promise<void> {
    const response = await fetch('/api/v1/generate/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!response.ok || !response.body) {
      throw new Error(`生成请求失败：${response.status}`)
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // SSE 以空行分隔事件，逐块解析 data: 行
      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? ''
      for (const part of parts) {
        const line = part.split('\n').find((l) => l.startsWith('data: '))
        if (!line) continue
        try {
          onEvent(JSON.parse(line.slice(6)) as GenerateStreamEvent)
        } catch {
          // 忽略无法解析的片段
        }
      }
    }
  },
  parsePrd(file: File) {
    const form = new FormData()
    form.append('file', file)
    return client.post<any, ParsedPrd>('/parse-prd', form, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
  listCases() { return client.get<any, CaseRecord[]>('/cases') },
  reviewCase(caseId: string, data: { status: 'approved' | 'rejected'; reject_reason?: string }) {
    return client.post<any, { status: string }>(`/cases/${caseId}/review`, data)
  },
  exportCases(cases: CaseRecord[] | GeneratedTestCase[]) {
    return client.post<any, Blob>('/cases/export', { cases }, { responseType: 'blob' })
  },
  statsOverview() { return client.get<any, StatsOverview>('/stats/overview') },
}
