<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { generationApi, type CaseRecord } from '@/api/generation'

const cases = ref<CaseRecord[]>([])
const loading = ref(false)
const filterTab = ref<'all' | 'pending' | 'approved' | 'rejected'>('all')

const rejectReasons = [
  { value: 'field_hallucination', label: '字段幻觉' },
  { value: 'rule_hallucination', label: '规则幻觉' },
  { value: 'context_missing', label: '上下文缺失' },
  { value: 'style_mismatch', label: '风格不一致' },
  { value: 'discard', label: '丢弃' },
]

// 按批次分组，并应用当前审核状态筛选。
const batches = computed(() => {
  const map: Record<string, CaseRecord[]> = {}
  for (const c of cases.value) {
    if (filterTab.value === 'pending' && c.review) continue
    if (filterTab.value === 'approved' && c.review?.status !== 'approved') continue
    if (filterTab.value === 'rejected' && c.review?.status !== 'rejected') continue

    const bid = c.batch_id || 'unknown'
    if (!map[bid]) map[bid] = []
    map[bid].push(c)
  }
  return Object.entries(map).map(([bid, items]) => {
    const reviewed = items.filter(c => c.review).length
    const approved = items.filter(c => c.review?.status === 'approved').length
    return {
      batch_id: bid,
      req_text: items[0]?.req_text || '',
      created_at: items[0]?.created_at || '',
      total: items.length,
      reviewed,
      approved,
      items,
    }
  }).sort((a, b) => b.created_at.localeCompare(a.created_at))
})

const totalReviewed = computed(() => cases.value.filter(c => c.review).length)
const totalApproved = computed(() => cases.value.filter(c => c.review?.status === 'approved').length)
const usabilityRate = computed(() => {
  return totalReviewed.value > 0 ? Math.round((totalApproved.value / totalReviewed.value) * 100) : 0
})

onMounted(async () => {
  loading.value = true
  try { cases.value = await generationApi.listCases() }
  catch { ElMessage.error('加载失败') }
  finally { loading.value = false }
})

async function approveCase(caseId: string) {
  try {
    await generationApi.reviewCase(caseId, { status: 'approved' })
    const c = cases.value.find(x => x.id === caseId)
    if (c) c.review = { status: 'approved' }
    return true
  } catch (e: any) {
    ElMessage.error(e.message)
    return false
  }
}

async function rejectCase(caseId: string, reason: string) {
  try {
    await generationApi.reviewCase(caseId, { status: 'rejected', reject_reason: reason })
    const c = cases.value.find(x => x.id === caseId)
    if (c) c.review = { status: 'rejected', reject_reason: reason }
    return true
  } catch (e: any) {
    ElMessage.error(e.message)
    return false
  }
}

async function approveAllInBatch(items: CaseRecord[]) {
  let success = 0
  for (const c of items) {
    if (!c.review && await approveCase(c.id)) success += 1
  }
  ElMessage.success(`批量通过完成，成功 ${success} 条`)
}

async function rejectAllInBatch(items: CaseRecord[], reason: string) {
  let success = 0
  for (const c of items) {
    if (!c.review && await rejectCase(c.id, reason)) success += 1
  }
  ElMessage.success(`批量拒绝完成，成功 ${success} 条`)
}
</script>

<template>
  <div class="review-view" v-loading="loading">
    <h2 style="margin-bottom:16px">审核标注</h2>
    <div class="stats-bar">
      <el-statistic title="总用例" :value="cases.length" />
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

    <div v-if="!batches.length && !loading">
      <el-empty description="暂无用例，请先生成" />
    </div>

    <div v-for="batch in batches" :key="batch.batch_id" class="batch-card">
      <div class="batch-header">
        <div>
          <strong class="batch-name">{{ batch.req_text?.slice(0, 60) || '未命名需求' }}</strong>
          <span class="batch-meta-info">{{ batch.total }} 条 · {{ batch.created_at?.slice(0, 16) }}</span>
        </div>
        <div class="batch-actions">
          <span class="batch-progress">已审核 {{ batch.reviewed }}/{{ batch.total }}</span>
          <el-button size="small" type="success" @click="approveAllInBatch(batch.items)">全部通过</el-button>
          <el-popover placement="bottom" :width="220" trigger="click">
            <template #reference>
              <el-button size="small" type="danger">全部拒绝</el-button>
            </template>
            <div style="font-size:13px;margin-bottom:8px">选择拒绝原因：</div>
            <el-button v-for="r in rejectReasons" :key="r.value" size="small" style="margin:2px" @click="rejectAllInBatch(batch.items, r.value)">{{ r.label }}</el-button>
          </el-popover>
        </div>
      </div>

      <el-collapse>
        <el-collapse-item :title="`展开 ${batch.total} 条用例`">
          <div v-for="c in batch.items" :key="c.id" class="review-item" :class="{ approved: c.review?.status === 'approved', rejected: c.review?.status === 'rejected' }">
            <div class="ri-header">
              <span class="ri-title">{{ c.title }}</span>
              <el-tag v-if="c.review?.status === 'approved'" type="success" size="small">✓</el-tag>
              <el-tag v-else-if="c.review?.status === 'rejected'" type="danger" size="small">✗ {{ rejectReasons.find(r => r.value === c.review?.reject_reason)?.label || '' }}</el-tag>
              <template v-else>
                <el-button size="small" type="success" @click="approveCase(c.id)" style="margin-left:8px">通过</el-button>
                <el-popover placement="bottom" :width="200" trigger="click">
                  <template #reference>
                    <el-button size="small" type="danger">不可用</el-button>
                  </template>
                  <el-button v-for="r in rejectReasons" :key="r.value" size="small" style="margin:2px" @click="rejectCase(c.id, r.value)">{{ r.label }}</el-button>
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
