// token 数的紧凑展示：看板上动辄百万级，原样显示「8437291」既占地方又难读。
// 阈值取 10000 而非 1000：几千的数字直接看原值更准确，K 反而丢精度。
// null/undefined 返回「—」而不是 0——没有采集到数据和真的没消耗是两件事。
export function formatTokens(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 10_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}
