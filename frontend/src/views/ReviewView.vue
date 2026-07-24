<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { generationApi, type CaseRecord, type BatchSummary } from '@/api/generation'

const batches = ref<BatchSummary[]>([])
const batchItems = ref<Record<string, CaseRecord[]>>({})
const loadingBatch = ref<Record<string, boolean>>({})
const loading = ref(false)
const filterTab = ref<'all' | 'pending' | 'approved' | 'rejected'>('all')

const rejectReasons = [
  { value: 'field_hallucination', label: '字段幻觉' },
  { value: 'rule_hallucination', label: '规则幻觉' },
  { value: 'context_missing', label: '上下文缺失' },
  { value: 'style_mismatch', label: '风格不一致' },
  { value: 'discard', label: '丢弃' },
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
    loading: !!loadingBatch.value[b.batch_id],
    loaded: !!batchItems.value[b.batch_id],
  }
}))

// 顶部统计：来自汇总接口，不受懒加载影响，也不会被 200 上限截断。
const totalCases = computed(() => batches.value.reduce((s, b) => s + b.total, 0))
const totalReviewed = computed(() => batches.value.reduce((s, b) => s + b.reviewed, 0))
const totalApproved = computed(() => batches.value.reduce((s, b) => s + b.approved, 0))
const usabilityRate = computed(() => totalReviewed.value > 0 ? Math.round((totalApproved.value / totalReviewed.value) * 100) : 0)

async function fetchBatches() {
  loading.value = true
  try { batches.value = await generationApi.listBatches() }
  catch { ElMessage.error('加载失败') }
  finally { loading.value = false }
}

async function loadBatchItems(bid: string) {
  if (batchItems.value[bid] || loadingBatch.value[bid]) return
  loadingBatch.value[bid] = true
  try {
    batchItems.value[bid] = await generationApi.listCases(bid)
  } catch (e: any) {
    ElMessage.error(e?.message || '加载批次失败')
  } finally {
    loadingBatch.value[bid] = false
  }
}

onMounted(fetchBatches)

// 本地增量更新：审核后刷新单条 items，同时同步 batch 汇总里的 reviewed/approved 计数。
function bumpBatchStats(bid: string, prev: CaseRecord['review'], next: CaseRecord['review']) {
  const b = batches.value.find(x => x.batch_id === bid)
  if (!b) return
  const wasReviewed = !!prev
  const willBeReviewed = !!next
  if (!wasReviewed && willBeReviewed) b.reviewed += 1
  else if (wasReviewed && !willBeReviewed) b.reviewed = Math.max(0, b.reviewed - 1)
  const wasApproved = prev?.status === 'approved'
  const willBeApproved = next?.status === 'approved'
  if (!wasApproved && willBeApproved) b.approved += 1
  else if (wasApproved && !willBeApproved) b.approved = Math.max(0, b.approved - 1)
}

async function approveCase(caseId: string, bid: string) {
  try {
    await generationApi.reviewCase(caseId, { status: 'approved' })
    const items = batchItems.value[bid]
    const c = items?.find(x => x.id === caseId)
    if (c) { bumpBatchStats(bid, c.review, { status: 'approved' }); c.review = { status: 'approved' } }
    return true
  } catch (e: any) {
    ElMessage.error(e.message)
    return false
  }
}

async function rejectCase(caseId: string, bid: string, reason: string) {
  try {
    await generationApi.reviewCase(caseId, { status: 'rejected', reject_reason: reason })
    const items = batchItems.value[bid]
    const c = items?.find(x => x.id === caseId)
    if (c) { bumpBatchStats(bid, c.review, { status: 'rejected', reject_reason: reason }); c.review = { status: 'rejected', reject_reason: reason } }
    return true
  } catch (e: any) {
    ElMessage.error(e.message)
    return false
  }
}

async function approveAllInBatch(bid: string, items: CaseRecord[]) {
  let success = 0
  for (const c of items) {
    if (!c.review && await approveCase(c.id, bid)) success += 1
  }
  ElMessage.success(`批量通过完成，成功 ${success} 条`)
}

async function rejectAllInBatch(bid: string, items: CaseRecord[], reason: string) {
  let success = 0
  for (const c of items) {
    if (!c.review && await rejectCase(c.id, bid, reason)) success += 1
  }
  ElMessage.success(`批量拒绝完成，成功 ${success} 条`)
}
</script>

<template>
  <div class="review-view" v-loading="loading">
    <h2 style="margin-bottom:16px">审核标注</h2>
    <div class="stats-bar">
      <el-statistic title="总用例" :value="totalCases" />
      <el-statistic title="已审核" :value="totalReviewed" />
      <el-statistic title="通过" :value="totalApproved" />
      <el-statistic title="可用率">
        <template #default><span :style="{color: usabilityRate >= 85 ? '#67C23A' : '#E6A23C'}">{{ usabilityRate }}%</span></template>
      </el-statistic>
    </div>

    <el-tabs v-model="filterTab" style="margin-bottom:12px">
      <el-tab-pane label="全部" name="all" />
      <el-tab-pane label="待审核" name="pending" />
      <el-tab-pane label="已通过" name="approved" />
      <el-tab-pane label="不可用" name="rejected" />
    </el-tabs>

    <div v-if="!displayBatches.length && !loading">
      <el-empty description="暂无用例，请先生成" />
    </div>

    <div v-for="batch in displayBatches" :key="batch.batch_id" class="batch-card">
      <div class="batch-header">
        <div>
          <strong class="batch-name">{{ batch.req_text?.slice(0, 60) || '未命名需求' }}</strong>
          <span class="batch-meta-info">{{ batch.total }} 条 · {{ batch.created_at?.slice(0, 16) }}</span>
        </div>
        <div class="batch-actions">
          <span class="batch-progress">已审核 {{ batch.reviewed }}/{{ batch.total }}</span>
          <el-button size="small" type="success" :disabled="!batch.loaded" @click="approveAllInBatch(batch.batch_id, batch.items)">全部通过</el-button>
          <el-popover placement="bottom" :width="220" trigger="click" :disabled="!batch.loaded">
            <template #reference>
              <el-button size="small" type="danger" :disabled="!batch.loaded">全部拒绝</el-button>
            </template>
            <div style="font-size:13px;margin-bottom:8px">选择拒绝原因：</div>
            <el-button v-for="r in rejectReasons" :key="r.value" size="small" style="margin:2px" @click="rejectAllInBatch(batch.batch_id, batch.items, r.value)">{{ r.label }}</el-button>
          </el-popover>
        </div>
      </div>

      <el-collapse @change="(val: string | string[]) => (Array.isArray(val) ? val : [val]).includes(batch.batch_id) && loadBatchItems(batch.batch_id)">
        <el-collapse-item :title="`展开 ${batch.total} 条用例`" :name="batch.batch_id">
          <div v-if="batch.loading" style="text-align:center;color:#909399;padding:10px">加载中...</div>
          <div v-else-if="!batch.items.length" style="text-align:center;color:#909399;padding:10px">
            {{ batch.loaded ? '当前筛选下无匹配用例' : '暂无数据' }}
          </div>
          <div v-else v-for="c in batch.items" :key="c.id" class="review-item" :class="{ approved: c.review?.status === 'approved', rejected: c.review?.status === 'rejected' }">
            <div class="ri-header">
              <span class="ri-title">{{ c.title }}</span>
              <el-tag v-if="c.review?.status === 'approved'" type="success" size="small">✓</el-tag>
              <el-tag v-else-if="c.review?.status === 'rejected'" type="danger" size="small">✗ {{ rejectReasons.find(r => r.value === c.review?.reject_reason)?.label || '' }}</el-tag>
              <template v-else>
                <el-button size="small" type="success" @click="approveCase(c.id, batch.batch_id)" style="margin-left:8px">通过</el-button>
                <el-popover placement="bottom" :width="200" trigger="click">
                  <template #reference>
                    <el-button size="small" type="danger">不可用</el-button>
                  </template>
                  <el-button v-for="r in rejectReasons" :key="r.value" size="small" style="margin:2px" @click="rejectCase(c.id, batch.batch_id, r.value)">{{ r.label }}</el-button>
                </el-popover>
              </template>
            </div>
            <div class="ri-body">
              <div v-if="c.precondition" class="ri-line">前置：{{ c.precondition }}</div>
              <div v-if="c.expected_result" class="ri-line">预期：{{ c.expected_result }}</div>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>
  </div>
</template>

<style scoped>
.review-view { max-width: 1024px; margin: 0 auto; }
.stats-bar { display: flex; gap: 40px; margin: 20px 0; padding: 16px; background: #fff; border-radius: 8px; }
.batch-card { border: 1px solid #e4e7ed; border-radius: 8px; padding: 14px; margin-bottom: 16px; background: #fff; }
.batch-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; gap: 12px; }
.batch-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; white-space: nowrap; }
.batch-name { font-size: 14px; display: block; }
.batch-meta-info { display: block; font-size: 12px; color: #909399; margin-top: 2px; }
.batch-req { display: block; font-size: 12px; color: #909399; margin-top: 4px; }
.batch-time { display: block; font-size: 11px; color: #c0c4cc; }
.batch-progress { font-size: 12px; color: #909399; }
.review-item { padding: 8px 12px; border-bottom: 1px solid #f0f0f0; }
.review-item:last-child { border-bottom: none; }
.review-item.approved { background: #f0f9eb; }
.review-item.rejected { background: #fef0f0; }
.ri-header { display: flex; align-items: center; gap: 8px; }
.ri-title { font-size: 13px; font-weight: 600; flex: 1; }
.ri-body { margin-top: 4px; padding-left: 4px; }
.ri-line { font-size: 12px; color: #909399; }
</style>
