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
      // 模块拆分完成后推送拆出的模块清单，让前端展示「本次拆成了哪些模块」。
      type: 'modules'
      modules: string[]
    }
  // 每个模块（agent）开始生成：前端据 index 建/激活对应 agent 卡片。
  | { type: 'module_start'; index: number; module: string }
  // 某模块的实时流式文本：按 index 归档到对应 agent 卡片的流缓冲区。
  | { type: 'module_chunk'; index: number; text: string }
  // 某模块的思考流（reasoning_content）：思考阶段实时下发，前端展示 🤔 思考中，
  // 避免思考期干等"等待模型输出"。思考文本不参与用例解析。
  | { type: 'module_thinking'; index: number; text: string }
  // 某模块生成完成：带该模块解析出的用例，前端把卡片从流式文本切换为用例列表。
  // elapsed 为该模块生成耗时（秒）。
  | { type: 'module_done'; index: number; module: string; cases: GeneratedTestCase[]; elapsed?: number }
  // 某模块生成失败：卡片标记为失败态。elapsed 为失败前耗时（秒）。
  | { type: 'module_failed'; index: number; module: string; elapsed?: number }
  // ── 评审阶段的多 agent 事件（与生成阶段同构）：按模块分组，每组一个评审 agent 并行跑，
  //    各自一张卡片实时流式展示「AI 正在保留/删除哪条、理由是什么」。 ──
  | { type: 'review_start'; index: number; module: string }
  | { type: 'review_thinking'; index: number; text: string }
  | { type: 'review_chunk'; index: number; text: string }
  // 评审完成：kept/deleted 为该模块保留/删除条数，供卡片小结展示。
  | { type: 'review_done'; index: number; module: string; kept?: number; deleted?: number; elapsed?: number }
  | { type: 'review_failed'; index: number; module: string; elapsed?: number }
  // ── 补充阶段的多 agent 事件：被删场景按模块、遗漏场景单独，各一个补充 agent 并行生成。──
  | { type: 'supplement_start'; index: number; module: string }
  | { type: 'supplement_thinking'; index: number; text: string }
  | { type: 'supplement_chunk'; index: number; text: string }
  // 补充完成：count 为该 agent 新生成的用例条数（去重前）。
  | { type: 'supplement_done'; index: number; module: string; count?: number; elapsed?: number }
  | { type: 'supplement_failed'; index: number; module: string; elapsed?: number }
  | {
      // 检索完成后立即推送，让前端在等生成时就能显示命中的知识。
      // complete 事件里也会带同样两个字段，用于重连兜底。
      type: 'knowledge'
      knowledge_used: Record<string, number>
      knowledge_matches: KnowledgeMatches
    }
  | {
      type: 'complete'
      cases: GeneratedTestCase[]
      knowledge_used: Record<string, number>
      knowledge_matches: KnowledgeMatches
      validation_warnings: unknown[] | null
      elapsed?: number
    }
  | { type: 'error'; message: string }

export interface CaseRecord extends TestCase {
  batch_id?: string | null
  req_text?: string | null
  created_at?: string
  // 审核阶段被人工微调过的用例会打上 edited=true，前端用它挂一个「已编辑」小 tag，
  // 也让统计口径区分「AI 直接可用」和「AI+人工微调后可用」。
  edited?: boolean
  edited_at?: string | null
  review?: {
    status: 'approved' | 'rejected'
    reject_reason?: string | null
  } | null
}

export interface BatchSummary {
  batch_id: string
  total: number
  reviewed: number
  approved: number
  req_text: string
  created_at: string
  // 该批次的 token 消耗。用量统计上线前的历史批次没有流水，此时为 null——
  // 前端对 null 不显示，不拿 0 冒充「这批没花 token」。
  tokens?: number | null
}

// 按阶段拆分的 token 消耗，用来回答「钱花在哪个环节」。
export interface TokenUsageByStage {
  stage: string
  label: string
  tokens: number
  calls: number
}

export interface TokenUsage {
  today_tokens: number
  week_tokens: number
  total_tokens: number
  // 推理模型的思考 token（已含在 completion 内），用于判断高 reasoning_effort 值不值。
  reasoning_tokens: number
  calls: number
  by_stage: TokenUsageByStage[]
  // 首条流水的时间。为 null 说明还没采到数据，前端据此提示「统计自 X 起」，
  // 免得把「累计 0」误读成「一次都没生成过」。
  since: string | null
}

export interface StatsOverview {
  total_cases: number
  reviewed_cases: number
  approved_cases: number
  rejected_cases: number
  usability_rate: number
  hallucination_distribution: Record<string, number>
  generation_count: number
  token_usage?: TokenUsage
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
      let event: GenerateStreamEvent
      try {
        event = JSON.parse(line.slice(6)) as GenerateStreamEvent
      } catch {
        // 忽略无法解析的片段
        continue
      }
      // onEvent 可能通过 throw 通知上层（error 事件），必须放在 JSON.parse 的
      // try/catch 之外——否则这个有意的抛出会被当成"解析失败"吞掉，前端就既不
      // 提示成功也不提示失败。
      onEvent(event)
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
  // 传入 batchId 时按批次拉全量用例，无 batchId 时兼容旧调用（最多 200 条概览）。
  // 历史/审核页应先调 listBatches 拿汇总，再对展开的那一批调 listCases(batchId)。
  listCases(batchId?: string) {
    return client.get<any, CaseRecord[]>('/cases', batchId ? { params: { batch_id: batchId } } : undefined)
  },
  // 拉所有批次的汇总（总数/已审核/通过数/需求文本/时间），供历史与审核页折叠态渲染。
  listBatches() { return client.get<any, BatchSummary[]>('/cases/batches') },
  reviewCase(caseId: string, data: { status: 'approved' | 'rejected'; reject_reason?: string }) {
    return client.post<any, { status: string }>(`/cases/${caseId}/review`, data)
  },
  updateCase(caseId: string, data: { title?: string; priority?: string | null; precondition?: string | null; steps?: string | null; expected_result?: string | null }) {
    return client.patch<any, CaseRecord>(`/cases/${caseId}`, data)
  },
  // 审核时手动插入用例。传前后两条 case 的 id 作为锚点，服务端算 sort_order 中点。
  // 首/末尾插入时只传一侧即可；都不传等价于批次末尾追加。
  createCase(data: { batch_id: string; title: string; priority?: string | null; precondition?: string | null; steps?: string | null; expected_result?: string | null; prev_case_id?: string | null; next_case_id?: string | null }) {
    return client.post<any, CaseRecord>('/cases', data)
  },
  exportCases(cases: CaseRecord[] | GeneratedTestCase[]) {
    return client.post<any, Blob>('/cases/export', { cases }, { responseType: 'blob' })
  },
  statsOverview() { return client.get<any, StatsOverview>('/stats/overview') },
}
