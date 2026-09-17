import client from './client'
import type { AuthUser, LoginResult } from '@/types/auth'

export const authApi = {
  login(username: string, password: string) {
    return client.post<any, LoginResult>('/auth/login', { username, password })
  },
  me() {
    return client.get<any, AuthUser>('/auth/me')
  },
  changePassword(old_password: string, new_password: string) {
    return client.post('/auth/change-password', { old_password, new_password })
  },
}
