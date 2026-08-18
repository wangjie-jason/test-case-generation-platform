import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { generationApi, type CaseRecord, type BatchSummary } from '@/api/generation'

// 加载态最短展示时长（毫秒）：本地请求常在 100ms 内返回，不兜一下就只看到一闪
const MIN_LOADING_MS = 200

/**
 * 批次列表 + 按批懒加载用例。生成历史页与审核页共用。
 *
 * 两页的交互模型相同：先拉 /cases/batches 汇总渲染折叠卡片，点开某批时才按
 * batch_id 拉该批全量用例（老实现一次拉 /cases 写死上限，大批次会被截断）。
 * 抽出来之前两页各有一份逐字相同的实现，改一处漏一处。
 *
 * @param failMessage 拉汇总失败时的提示文案——两页措辞不同（生成页说"生成历史"）。
 */
export function useBatchList(failMessage = '加载失败') {
  const batches = ref<BatchSummary[]>([])
  // 已加载过的批次用例，key 为 batch_id。作缓存用：收起再展开不重复请求。
  const batchItems = ref<Record<string, CaseRecord[]>>({})
  const loadingBatch = ref<Record<string, boolean>>({})
  const expandedBatch = ref<Record<string, boolean>>({})
  // 页面级加载态（拉汇总时），与 loadingBatch 的单批加载态是两回事
  const loading = ref(false)

  async function fetchBatches() {
    loading.value = true
    try {
      batches.value = await generationApi.listBatches()
    } catch {
      ElMessage.error(failMessage)
    } finally {
      loading.value = false
    }
  }

  async function loadBatchItems(bid: string) {
    if (batchItems.value[bid] || loadingBatch.value[bid]) return
    loadingBatch.value[bid] = true
    // 本地后端往往 100ms 内就返回，骨架一闪而过反而像页面在抖；
    // 给个最短展示时长，让加载态至少完整出现一次。
    const startedAt = performance.now()
    try {
      const items = await generationApi.listCases(bid)
      const elapsed = performance.now() - startedAt
      if (elapsed < MIN_LOADING_MS) {
        await new Promise(r => setTimeout(r, MIN_LOADING_MS - elapsed))
      }
      batchItems.value[bid] = items
    } catch (e: any) {
      ElMessage.error(e?.message || '加载批次失败')
    } finally {
      loadingBatch.value[bid] = false
    }
  }

  // 批次标题行即折叠头：点一次展开并懒加载（已加载过只切显隐），再点收起。
  function toggleBatch(bid: string) {
    expandedBatch.value[bid] = !expandedBatch.value[bid]
    if (expandedBatch.value[bid]) loadBatchItems(bid)
  }

  // 清掉懒加载缓存与展开态。「刷新」和「生成完成后自动重拉」都要用：
  // 不清的话已展开的批次仍显示旧结果。
  function resetCache() {
    batchItems.value = {}
    expandedBatch.value = {}
  }

  return {
    batches,
    batchItems,
    loadingBatch,
    expandedBatch,
    loading,
    fetchBatches,
    loadBatchItems,
    toggleBatch,
    resetCache,
  }
}
