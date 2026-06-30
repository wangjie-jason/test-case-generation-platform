export interface ReviewRecord {
  id: string
  case_id: string
  status: 'approved' | 'rejected'
  reject_reason: 'field_hallucination' | 'rule_hallucination' | 'context_missing' | 'style_mismatch' | null
  reviewer_comment: string | null
  reviewed_at: string
}
