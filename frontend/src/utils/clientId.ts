// 匿名客户端标识（归属者 ID）。存于 localStorage，用于多人/多浏览器的任务隔离。
// 命名保持中立：将来接入登录账号后，可改由登录态提供 owner_id，调用方无需改动。
const STORAGE_KEY = 'tcg_client_id'

export function getClientId(): string {
  let id = localStorage.getItem(STORAGE_KEY)
  if (!id) {
    id = (typeof crypto !== 'undefined' && crypto.randomUUID)
      ? crypto.randomUUID()
      : `c_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`
    localStorage.setItem(STORAGE_KEY, id)
  }
  return id
}
