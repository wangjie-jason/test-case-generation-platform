import client from './client'
import type { AuthUser } from '@/types/auth'

export interface AdminCreateUser {
  username: string
  password: string
  display_name?: string
  is_admin?: boolean
}

export const adminApi = {
  listUsers() {
    return client.get<any, AuthUser[]>('/admin/users')
  },
  createUser(data: AdminCreateUser) {
    return client.post<any, AuthUser>('/admin/users', data)
  },
  updateUser(id: string, data: { display_name?: string | null; is_active?: boolean; is_admin?: boolean }) {
    return client.patch<any, AuthUser>(`/admin/users/${id}`, data)
  },
  resetPassword(id: string, new_password: string) {
    return client.post<any, { message: string }>(`/admin/users/${id}/reset-password`, { new_password })
  },
}
