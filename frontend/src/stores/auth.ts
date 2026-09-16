import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi } from '@/api/auth'
import type { AuthUser } from '@/types/auth'
import { clearToken, getToken, setToken } from '@/utils/authToken'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(getToken())
  const user = ref<AuthUser | null>(null)
  // 同一次刷新里多个路由守卫/组件并发进入时，只发一次 /auth/me。
  let loading: Promise<void> | null = null

  function setSession(accessToken: string, u: AuthUser) {
    token.value = accessToken
    user.value = u
    setToken(accessToken)
  }

  async function login(username: string, password: string) {
    const res = await authApi.login(username, password)
    setSession(res.access_token, res.user)
  }

  function logout() {
    token.value = ''
    user.value = null
    clearToken()
  }

  // 路由守卫调用：有 token 就拉一次 /auth/me 恢复用户（同时校验有效性）。
  async function ensureLoaded(): Promise<void> {
    if (!token.value) {
      user.value = null
      return
    }
    if (user.value) return
    if (!loading) {
      loading = (async () => {
        try {
          user.value = await authApi.me()
        } catch {
          // 401 拦截器已负责跳登录；这里只保证状态干净。
          logout()
        } finally {
          loading = null
        }
      })()
    }
    await loading
  }

  return { token, user, login, logout, ensureLoaded }
})
