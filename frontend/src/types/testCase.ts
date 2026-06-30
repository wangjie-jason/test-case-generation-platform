export interface KnowledgeRef {
  kb_id?: string
  type?: string
  id?: string
  text?: string
  score?: number
}

export interface GeneratedTestCase {
  id?: string
  scenario?: string | null
  title?: string
  precondition?: string | null
  steps?: string | unknown[] | null
  expected_result?: string | null
  source?: 'manual' | 'ai'
  quality_score?: number | null
  knowledge_refs?: KnowledgeRef[]
  priority?: 'P0' | 'P1' | 'P2' | 'P3' | string
  error?: string
  raw?: string
}

export interface TestCase extends GeneratedTestCase {
  id: string
  title: string
  source: 'manual' | 'ai'
}
