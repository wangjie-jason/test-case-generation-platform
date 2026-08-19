import { computed, type Ref } from 'vue'
import type { KnowledgeMatches } from '@/api/generation'

export interface KnowledgeCounts {
  field_dicts_count?: number
  business_rules_count?: number
  state_machines_count?: number
  term_mappings_count?: number
  prd_chunks_count?: number
  defect_chunks_count?: number
  historical_cases_count?: number
}

export interface MatchGroup {
  key: string
  title: string
  countKey: keyof KnowledgeCounts
  items: Array<Record<string, unknown>>
}

/**
 * 知识库命中信息的两类展示工具：
 * - summary：把命中条数拼成可读字符串（「3 字段 / 2 规则 / ... / 无」）
 * - groups / hasAny：按组分类渲染（每组一块卡片），含过滤逻辑
 * - title / description：单条命中的标题/描述生成（含字段名兜底、长度截断）
 *
 * 之前在 GenerationView.vue 里散落，改 prompt/扩一类知识时容易漏。
 */
export function useKnowledgeMatches(
  knowledgeCounts: Ref<KnowledgeCounts>,
  knowledgeMatches: Ref<KnowledgeMatches>,
) {
  const summary = computed(() => {
    const c = knowledgeCounts.value
    const p: string[] = []
    if (c.field_dicts_count) p.push(`${c.field_dicts_count} 字段`)
    if (c.business_rules_count) p.push(`${c.business_rules_count} 规则`)
    if (c.state_machines_count) p.push(`${c.state_machines_count} 状态`)
    if (c.term_mappings_count) p.push(`${c.term_mappings_count} 术语`)
    if (c.prd_chunks_count) p.push(`${c.prd_chunks_count} PRD`)
    if (c.defect_chunks_count) p.push(`${c.defect_chunks_count} 缺陷`)
    if (c.historical_cases_count) p.push(`${c.historical_cases_count} 历史用例`)
    return p.join(' / ') || '无'
  })

  const groups = computed<MatchGroup[]>(() => {
    const m = knowledgeMatches.value
    const c = knowledgeCounts.value
    const raw: MatchGroup[] = [
      { key: 'field_dicts', title: '字段字典', countKey: 'field_dicts_count', items: m.field_dicts || [] },
      { key: 'business_rules', title: '业务规则', countKey: 'business_rules_count', items: m.business_rules || [] },
      { key: 'state_machines', title: '状态流转', countKey: 'state_machines_count', items: m.state_machines || [] },
      { key: 'term_mappings', title: '术语映射', countKey: 'term_mappings_count', items: m.term_mappings || [] },
      { key: 'prd_chunks', title: 'PRD片段', countKey: 'prd_chunks_count', items: m.prd_chunks || [] },
      { key: 'defect_chunks', title: '缺陷记录', countKey: 'defect_chunks_count', items: m.defect_chunks || [] },
      { key: 'historical_cases', title: '历史用例', countKey: 'historical_cases_count', items: m.historical_cases || [] },
    ]
    // 没条数、没明细的组不展示，避免一堆空标题
    return raw.filter(g => g.items.length || knowledgeCounts.value[g.countKey])
  })

  const hasAny = computed(() => groups.value.some(g => g.items.length))

  function title(groupKey: string, item: Record<string, unknown>): string {
    if (groupKey === 'field_dicts') return `${item.display_name || ''}${item.field_name ? `（${item.field_name}）` : ''}` || '字段'
    if (groupKey === 'business_rules') return String(item.rule_name || '业务规则')
    if (groupKey === 'state_machines') return `${item.entity || '对象'}：${item.from_state || '-'} → ${item.to_state || '-'}`
    if (groupKey === 'term_mappings') return `${item.ui_term || '术语'} → ${item.tech_field || '-'}`
    if (groupKey === 'defect_chunks') return String(item.title || '缺陷片段')
    if (groupKey === 'historical_cases') return '相似历史用例'
    return String(item.filename || item.id || '知识片段')
  }

  function description(groupKey: string, item: Record<string, unknown>): string {
    const value = item.description || item.expression || item.condition || item.mapping_desc || item.text || ''
    const text = String(value || '')
    if (!text) return groupKey === 'field_dicts' && item.data_type ? `类型：${item.data_type}` : ''
    return text.length > 160 ? `${text.slice(0, 160)}...` : text
  }

  return { summary, groups, hasAny, title, description }
}
