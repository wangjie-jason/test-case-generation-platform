// 登录 token 的本地存储与 401 统一处理。与旧的匿名 clientId 不同，token 由服务端
// 登录签发，是所有接口（含绕过 axios 的 SSE fetch）的鉴权凭证。
const STORAGE_KEY = 'tcg_token'

export function getToken(): string {
  return localStorage.getItem(STORAGE_KEY) ?? ''
}

export function setToken(token: string): void {
  localStorage.setItem(STORAGE_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(STORAGE_KEY)
}

// 401（含过期、停用、伪造）的统一收口：清凭证并整页跳到登录页。
// 用 location 跳转而非 router，是为了让 axios 拦截器和 SSE fetch 这两处
// 不依赖 pinia/router 实例也能复用同一条逻辑。
export function redirectToLogin(): void {
  clearToken()
  if (window.location.pathname.startsWith('/login')) return
  const here = window.location.pathname + window.location.search
  window.location.replace(`/login?redirect=${encodeURIComponent(here)}`)
}
