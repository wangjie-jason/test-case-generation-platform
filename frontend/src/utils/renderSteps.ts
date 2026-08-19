// 用例的 steps 可能是字符串（新结构）或数组（老的 GeneratedTestCase 结构），
// 生成页 / 历史页 / 审核页四处都要展示，逐处内联三元容易改一处漏三处，故收一处。
// 非字符串一律 JSON.stringify，与拆分前的行为保持一致。
export function renderSteps(steps: unknown): string {
  if (steps == null) return ''
  if (typeof steps === 'string') return steps
  return JSON.stringify(steps)
}
