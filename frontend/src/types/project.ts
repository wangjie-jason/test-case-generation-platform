export type KbVisibility = 'team' | 'personal'

export interface KnowledgeBase {
  id: string
  name: string
  description: string | null
  owner_id: string
  visibility: KbVisibility
  owner_name: string | null
  can_manage: boolean
  created_at: string
  updated_at: string
}
