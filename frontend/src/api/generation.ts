import client from './client'
import { getClientId } from '@/utils/clientId'
import type { GeneratedTestCase, TestCase } from '@/types/testCase'

export interface GenerateRequest {
  kb_ids: string[]
  requirement_text: string
  batch_name?: string
  client_id?: string
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

export interface GenerationTaskSummary {
  task_id: string
  title: string
  status: 'running' | 'done' | 'error'
  owner_id?: string | null
  created_at: string
}

// 读取 SSE 流并按事件回调。供首发请求与重连共用。
async function consumeSse(
  response: Response,
  onEvent: (event: GenerateStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    if (signal?.aborted) { await reader.cancel().catch(() => {}); break }
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
}

export const generationApi = {
  // 基于知识库补全需求，返回结构化完整需求（Markdown），供用户确认/编辑后再生成。
  clarify(data: GenerateRequest) {
    return client.post<any, { clarified_text: string }>('/generate/clarify', data)
  },
  // 启动后台生成任务，立即返回 task_id；任务脱离请求，刷新/切走后仍继续。
  startTask(data: GenerateRequest) {
    return client.post<any, GenerationTaskSummary>('/generate/async', { ...data, client_id: getClientId() })
  },
  // 列出本客户端仍在运行的任务，供刷新后「继续查看」。
  activeTasks() {
    return client.get<any, GenerationTaskSummary[]>('/generate/active', { params: { client_id: getClientId() } })
  },
  // 重连到指定任务的事件流：先重放已产生事件，再接收实时事件。
  async streamTask(taskId: string, onEvent: (event: GenerateStreamEvent) => void, signal?: AbortSignal): Promise<void> {
    const response = await fetch(`/api/v1/generate/stream/${taskId}`, { signal })
    if (!response.ok || !response.body) {
      throw new Error(`连接任务失败：${response.status}`)
    }
    await consumeSse(response, onEvent, signal)
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
