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
  // 产出阶段：'supplement' = 评审后针对被删/遗漏场景定向补充的用例。生成阶段的用例与
  // 加列前的历史用例都是空值——历史数据无法可靠反推，故不显示标签而非标成「生成」。
  origin?: 'supplement' | null
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
