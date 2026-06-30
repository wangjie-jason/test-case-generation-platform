export interface FieldDict {
  id: string; kb_id: string; field_name: string; display_name: string
  data_source: string | null; data_type: string; enum_values: string | null; description: string | null
  created_at: string; updated_at: string
}
export interface BusinessRule {
  id: string; kb_id: string; rule_name: string; rule_type: 'hard' | 'soft'
  expression: string; description: string | null; source: string | null
  created_at: string; updated_at: string
}
export interface StateMachine {
  id: string; kb_id: string; entity: string; from_state: string; to_state: string
  condition: string | null; created_at: string
}
export interface TermMapping {
  id: string; kb_id: string; ui_term: string; tech_field: string
  mapping_desc: string | null; created_at: string
}
export interface PrdDocument {
  id: string; kb_id: string; filename: string; file_format: string
  raw_text: string; chunk_count: number; created_at: string
}
export interface DefectRecord {
  id: string; kb_id: string; title: string; severity: 'critical' | 'major' | 'minor' | 'trivial'
  root_cause: string | null; description: string; related_case: string | null
  occurred_at: string | null; created_at: string
}
