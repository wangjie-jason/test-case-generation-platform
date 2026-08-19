<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useBatchList } from '@/composables/useBatchList'
import { useBatchReview } from '@/composables/useBatchReview'
import { useEditCaseDialog } from '@/composables/useEditCaseDialog'
import { useInsertCaseDialog } from '@/composables/useInsertCaseDialog'
import ReviewStatsBar from '@/components/review/ReviewStatsBar.vue'
import ReviewBatchCard from '@/components/review/ReviewBatchCard.vue'
import EditCaseDialog from '@/components/review/EditCaseDialog.vue'
import InsertCaseDialog from '@/components/review/InsertCaseDialog.vue'

const {
  batches, batchItems, loadingBatch, expandedBatch, loading,
  fetchBatches, toggleBatch,
} = useBatchList()
const filterTab = ref<'all' | 'pending' | 'approved' | 'rejected'>('all')

const rejectReasons = [
  { value: 'field_hallucination', label: '字段幻觉' },
  { value: 'rule_hallucination', label: '规则幻觉' },
  { value: 'context_missing', label: '上下文缺失' },
  { value: 'style_mismatch', label: '风格不一致' },
  { value: 'duplicate', label: '重复' },
]

// 展示的批次：把汇总里已知的 total/reviewed/approved 与懒加载的 items 拼起来。
// 用户切 filter tab 时，如果该批 items 还没拉，卡片头仍能显示进度（来自汇总）；
// 展开时才拉全量，再按 filter 过滤出可见 items（服务端就不再重复过滤了）。
const displayBatches = computed(() => batches.value.map(b => {
  const items = batchItems.value[b.batch_id] || []
  let filtered = items
  if (filterTab.value !== 'all') {
    filtered = items.filter(c => {
      if (filterTab.value === 'pending') return !c.review
      return c.review?.status === filterTab.value
    })
  }
  return {
    ...b,
    items: filtered,
    expanded: !!expandedBatch.value[b.batch_id],
    // 当前 tab 下的条数：全部由汇总的 total/reviewed/approved 推出，
    // 不依赖 items，所以批次没展开时也准（懒加载前 items 是空的）。
    visibleTotal: filterTab.value === 'all' ? b.total
      : filterTab.value === 'pending' ? b.total - b.reviewed
      : filterTab.value === 'approved' ? b.approved
      : b.reviewed - b.approved,
    loading: !!loadingBatch.value[b.batch_id],
    loaded: !!batchItems.value[b.batch_id],
  }
}))

// 顶部统计：来自汇总接口，不受懒加载影响，也不会被 200 上限截断。
const totalCases = computed(() => batches.value.reduce((s, b) => s + b.total, 0))
const totalReviewed = computed(() => batches.value.reduce((s, b) => s + b.reviewed, 0))
const totalApproved = computed(() => batches.value.reduce((s, b) => s + b.approved, 0))
const usabilityRate = computed(() => totalReviewed.value > 0 ? Math.round((totalApproved.value / totalReviewed.value) * 100) : 0)

onMounted(fetchBatches)

const LEADING_BRACKETS = /^[【（〔［｛「『《〈]/
function hangsPunctuation(title?: string) {
  return LEADING_BRACKETS.test(title || '')
}

const { approveCase, rejectCase, approveAllInBatch, rejectAllInBatch } = useBatchReview(batches, batchItems)
const edit = useEditCaseDialog(batchItems)
const insert = useInsertCaseDialog(batches, batchItems)

function openEdit(c: any, bid: string) { edit.open(c, bid) }
function openInsert(bid: string, insertAt: number) { insert.open(bid, insertAt) }
</script>

<template>
  <div class="review-view" v-loading="loading">
    <h2 style="margin-bottom:16px">审核标注</h2>
    <ReviewStatsBar
      :total-cases="totalCases"
      :total-reviewed="totalReviewed"
      :total-approved="totalApproved"
      :usability-rate="usabilityRate"
    />

    <el-tabs v-model="filterTab" style="margin-bottom:12px">
      <el-tab-pane label="全部" name="all" />
      <el-tab-pane label="待审核" name="pending" />
      <el-tab-pane label="已通过" name="approved" />
      <el-tab-pane label="不可用" name="rejected" />
    </el-tabs>

    <div v-if="!displayBatches.length && !loading">
      <el-empty description="暂无用例，请先生成" />
    </div>

    <ReviewBatchCard
      v-for="batch in displayBatches"
      :key="batch.batch_id"
      :batch="batch"
      :reject-reasons="rejectReasons"
      :hangs-punctuation="hangsPunctuation"
      :show-insert-slot="filterTab === 'all'"
      @toggle="toggleBatch"
      @approveAll="approveAllInBatch"
      @rejectAll="rejectAllInBatch"
      @approve="approveCase"
      @reject="rejectCase"
      @edit="openEdit"
      @insertAfter="openInsert"
    />
  </div>

  <EditCaseDialog
    v-model:visible="edit.dialogVisible.value"
    v-model:form="edit.form.value"
    :saving="edit.saving.value"
    @save="edit.save"
    @cancel="edit.dialogVisible.value = false"
  />
  <InsertCaseDialog
    v-model:visible="insert.dialogVisible.value"
    v-model:form="insert.form.value"
    :saving="insert.saving.value"
    @save="insert.save"
    @cancel="insert.dialogVisible.value = false"
  />
</template>

<style scoped>
.review-view { max-width: 1024px; margin: 0 auto; }
</style>
