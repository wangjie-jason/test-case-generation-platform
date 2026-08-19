import { ref, watch, computed, onUnmounted, type Ref } from 'vue'
import type { AgentState } from '@/stores/generation'

interface DurationTimerOptions {
  /** 有任务在跑时才开表，避免空转 */
  runningCount: Ref<number>
  /** 当前查看的任务是否在生成中 */
  isGenerating: Ref<boolean>
  /** 当前查看任务的开始时刻（ms），运行中据此现算总耗时 */
  taskStartedAt: Ref<number | null | undefined>
  /** 后端下发的总耗时（秒），完成后以它为权威值 */
  elapsed: Ref<number | null | undefined>
}

/**
 * 实时秒表 composable：让「运行时长」类计算属性随当前时间刷新。
 *
 * 场景：生成中需要展示「当前 agent 已跑 X 秒」「整批已跑 Y 秒」，这些值随真实
 * 时间增长而变化，但普通 computed 只在依赖变化时重算——把「当前时间」当依赖即可。
 *
 * 用法：
 *   const { now, formatDuration, agentSeconds, totalSeconds } = useDurationTimer({
 *     runningCount, isGenerating, taskStartedAt, elapsed,
 *   })
 *
 * - `now` 是驱动秒表刷新的 ref。
 * - `formatDuration(sec)` 把秒数格式化成「12.3s」/「1分23秒」。
 * - `agentSeconds(a)` 单个 agent 卡的显示耗时：运行中用秒表现算，完成后用后端权威值。
 * - `totalSeconds` 整批总耗时：完成后用后端值，运行中用秒表从 startedAt 现算。
 *
 * runningCount>0 时启动 200ms 定时器，=0 时关掉，避免空转。组件卸载时也会关。
 */
export function useDurationTimer({ runningCount, isGenerating, taskStartedAt, elapsed }: DurationTimerOptions) {
  const now = ref(Date.now())
  let timer: ReturnType<typeof setInterval> | null = null

  watch(runningCount, (n) => {
    if (n > 0 && timer == null) {
      timer = setInterval(() => { now.value = Date.now() }, 200)
    } else if (n === 0 && timer != null) {
      now.value = Date.now()  // 收表前再刷一次，让停下的瞬间数值贴近真实
      clearInterval(timer); timer = null
    }
  }, { immediate: true })
  onUnmounted(() => { if (timer != null) { clearInterval(timer); timer = null } })

  function formatDuration(sec: number | null | undefined): string {
    if (sec == null) return ''
    if (sec < 60) return `${sec}s`
    const m = Math.floor(sec / 60)
    const s = Math.round(sec % 60)
    return `${m}分${s}秒`
  }

  function agentSeconds(a: Pick<AgentState, 'status' | 'startedAt' | 'elapsed'>): number | null {
    if (a.status === 'running' && a.startedAt != null) {
      return Math.round((now.value - a.startedAt) / 100) / 10
    }
    return a.elapsed
  }

  const totalSeconds = computed<number | null>(() => {
    if (elapsed.value != null) return elapsed.value
    if (isGenerating.value && taskStartedAt.value != null) {
      return Math.round((now.value - taskStartedAt.value) / 100) / 10
    }
    return null
  })

  return { now, formatDuration, agentSeconds, totalSeconds }
}
