// 用例等级到 el-tag 类型的映射：P0 最高（红）、P1 次之（黄）、P2 与空值走灰。
// priority 允许为空——老库补列时统一置 NULL，那批用例事后无法可靠反推等级，
// 所以兜底到 info 而不是当成 P2，避免把「未知」显示成「低优先级」。
export function priorityTagType(priority?: string | null): 'danger' | 'warning' | 'info' {
  if (priority === 'P0') return 'danger'
  if (priority === 'P1') return 'warning'
  return 'info'
}
