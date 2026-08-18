// 触发浏览器下载一个内存 Blob。两处导出（当前结果 / 历史批次）原先各写一遍
// createElement('a') → createObjectURL → click → revokeObjectURL，
// 抽出来主要是为了 revoke 不会漏——漏了就是每次下载泄一个 blob URL。
export function saveBlob(blob: Blob, filename: string) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}
