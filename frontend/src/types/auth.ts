export interface AuthUser {
  id: string
  username: string
  display_name: string | null
  is_admin: boolean
  is_active: boolean
  created_at: string
}

export interface LoginResult {
  access_token: string
  token_type: string
  user: AuthUser
}
