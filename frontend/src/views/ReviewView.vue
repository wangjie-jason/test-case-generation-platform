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

// —— 用例编辑弹窗 ——
// 场景：有些生成结果只是文案上差几个字，直接拒绝可惜。允许四字段一起改。
// 产品口径：编辑 = AI 一次没产出合格结果，仍算「不通过」，只是拒绝原因记为 edited，
// 不污染 AI 可用率。可用率始终反映 AI 一次到位的能力。
const editDialogVisible = ref(false)
const editSaving = ref(false)
const editForm = ref<{ id: string; batch_id: string; title: string; precondition: string; steps: string; expected_result: string }>({
  id: '', batch_id: '', title: '', precondition: '', steps: '', expected_result: '',
})

function openEditDialog(c: CaseRecord, bid: string) {
  editForm.value = {
    id: c.id,
    batch_id: bid,
    title: c.title || '',
    precondition: c.precondition || '',
    // steps 可能是数组（老的 GeneratedTestCase 结构）或字符串，统一转成字符串给 textarea 用
    steps: Array.isArray(c.steps) ? (c.steps as unknown[]).map(String).join('\n') : (c.steps || ''),
    expected_result: c.expected_result || '',
  }
  editDialogVisible.value = true
}

async function saveEdit() {
  if (!editForm.value.title.trim()) {
    ElMessage.warning('标题不能为空')
    return
  }
  editSaving.value = true
  try {
    const updated = await generationApi.updateCase(editForm.value.id, {
      title: editForm.value.title,
      precondition: editForm.value.precondition,
      steps: editForm.value.steps,
      expected_result: editForm.value.expected_result,
    })
    const items = batchItems.value[editForm.value.batch_id]
    const c = items?.find(x => x.id === editForm.value.id)
    if (c) {
      c.title = updated.title
      c.precondition = updated.precondition
      c.steps = updated.steps
      c.expected_result = updated.expected_result
      c.edited = updated.edited
      c.edited_at = updated.edited_at
      // 编辑只改内容，不碰 review 记录——原始 reject_reason（如 context_missing）保留不丢
      // 可用率不受影响，导出时前端可辨认 edited=True 来包含补全后的用例
    }
    ElMessage.success('已保存，编辑标记已记录')
    editDialogVisible.value = false
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    editSaving.value = false
  }
}

// —— 手动插入用例弹窗 ——
// 场景：AI 漏了整个模块/功能，用户想在两条 case 之间补一条。
// 后端用 sort_order 中点定位，前端只负责传前后两条 case 的 id 作为锚点。
// 保存后新 case 直接插入到列表对应位置，batch 汇总的 total/reviewed/approved 各 +1
// （手动插入的默认 approved，无需再审）。
const insertDialogVisible = ref(false)
const insertSaving = ref(false)
const insertForm = ref<{ batch_id: string; prev_case_id: string | null; next_case_id: string | null; insertAt: number; title: string; precondition: string; steps: string; expected_result: string }>({
  batch_id: '', prev_case_id: null, next_case_id: null, insertAt: 0,
  title: '', precondition: '', steps: '', expected_result: '',
})

// insertAt 是要插入到本地 items 数组的目标下标：0=最开头，items.length=最末尾
function openInsertDialog(bid: string, insertAt: number) {
  const items = batchItems.value[bid] || []
  insertForm.value = {
    batch_id: bid,
    prev_case_id: insertAt > 0 ? items[insertAt - 1].id : null,
    next_case_id: insertAt < items.length ? items[insertAt].id : null,
    insertAt,
    title: '', precondition: '', steps: '', expected_result: '',
  }
  insertDialogVisible.value = true
}

async function saveInsert() {
  if (!insertForm.value.title.trim()) {
    ElMessage.warning('标题不能为空')
    return
  }
  insertSaving.value = true
  try {
    const created = await generationApi.createCase({
      batch_id: insertForm.value.batch_id,
      prev_case_id: insertForm.value.prev_case_id,
      next_case_id: insertForm.value.next_case_id,
      title: insertForm.value.title,
      precondition: insertForm.value.precondition,
      steps: insertForm.value.steps,
      expected_result: insertForm.value.expected_result,
    })
    const items = batchItems.value[insertForm.value.batch_id]
    if (items) {
      items.splice(insertForm.value.insertAt, 0, created)
    }
    // 手动插入的 case 后端直接 approved，同步 batch 汇总
    const b = batches.value.find(x => x.batch_id === insertForm.value.batch_id)
    if (b) { b.total += 1; b.reviewed += 1; b.approved += 1 }
    ElMessage.success('已插入用例')
    insertDialogVisible.value = false
  } catch (e: any) {
    ElMessage.error(e?.message || '插入失败')
  } finally {
    insertSaving.value = false
  }
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
          <template v-else>
            <!-- 首个用例前的插入位 -->
            <div class="insert-slot" v-if="filterTab === 'all'" @click="openInsertDialog(batch.batch_id, 0)">
              <span class="insert-line"></span><span class="insert-btn">+ 在此处插入用例</span><span class="insert-line"></span>
            </div>
            <template v-for="(c, idx) in batch.items" :key="c.id">
              <div class="review-item" :class="{ approved: c.review?.status === 'approved', rejected: c.review?.status === 'rejected' }">
                <div class="ri-header">
                  <span class="ri-title">{{ c.title }}</span>
                  <el-tag v-if="c.edited" size="small" type="warning" effect="plain" style="margin-right:4px">已编辑</el-tag>
                  <el-tag v-if="c.source === 'manual'" size="small" type="info" effect="plain" style="margin-right:4px">手动</el-tag>
                  <el-tag v-if="c.review?.status === 'approved'" type="success" size="small">✓</el-tag>
                  <el-tag v-else-if="c.review?.status === 'rejected'" type="danger" size="small">✗ {{ rejectReasons.find(r => r.value === c.review?.reject_reason)?.label || '' }}</el-tag>
                  <template v-else>
                    <el-button size="small" type="success" @click="approveCase(c.id, batch.batch_id)" style="margin-left:8px">通过</el-button>
                    <el-button size="small" @click="openEditDialog(c, batch.batch_id)" style="margin-left:4px">编辑</el-button>
                    <el-popover placement="bottom" :width="200" trigger="click">
                      <template #reference>
                        <el-button size="small" type="danger">不可用</el-button>
                      </template>
                      <el-button v-for="r in rejectReasons" :key="r.value" size="small" style="margin:2px" @click="rejectCase(c.id, batch.batch_id, r.value)">{{ r.label }}</el-button>
                    </el-popover>
                  </template>
                  <!-- 已通过或已拒绝的用例也允许编辑；编辑不改 review 状态，只改内容 -->
                  <el-button v-if="c.review" size="small" text @click="openEditDialog(c, batch.batch_id)" style="margin-left:4px">编辑</el-button>
                </div>
                <div class="ri-body">
                  <div v-if="c.precondition" class="ri-line">前置：{{ c.precondition }}</div>
                  <div v-if="c.expected_result" class="ri-line">预期：{{ c.expected_result }}</div>
                </div>
              </div>
              <!-- 每条 case 之后的插入位；筛选 tab 下隐藏（否则插入位置会错位） -->
              <div class="insert-slot" v-if="filterTab === 'all'" @click="openInsertDialog(batch.batch_id, idx + 1)">
                <span class="insert-line"></span><span class="insert-btn">+ 在此处插入用例</span><span class="insert-line"></span>
              </div>
            </template>
          </template>
        </el-collapse-item>
      </el-collapse>
    </div>
  </div>

  <!-- 编辑用例弹窗 -->
  <el-dialog v-model="editDialogVisible" title="编辑用例" width="600px" :close-on-click-modal="false">
    <el-form label-position="top" size="small">
      <el-form-item label="标题">
        <el-input v-model="editForm.title" placeholder="用例标题" :disabled="editSaving" />
      </el-form-item>
      <el-form-item label="前置条件">
        <el-input v-model="editForm.precondition" placeholder="前置条件（可选）" :disabled="editSaving" />
      </el-form-item>
      <el-form-item label="测试步骤">
        <el-input v-model="editForm.steps" type="textarea" :rows="4" placeholder="每行一步" :disabled="editSaving" />
      </el-form-item>
      <el-form-item label="预期结果">
        <el-input v-model="editForm.expected_result" type="textarea" :rows="3" placeholder="预期结果" :disabled="editSaving" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="editDialogVisible = false" :disabled="editSaving">取消</el-button>
      <el-button type="primary" @click="saveEdit" :loading="editSaving">保存</el-button>
    </template>
  </el-dialog>

  <!-- 插入用例弹窗 -->
  <el-dialog v-model="insertDialogVisible" title="插入新用例" width="600px" :close-on-click-modal="false">
    <el-form label-position="top" size="small">
      <el-form-item label="标题">
        <el-input v-model="insertForm.title" placeholder="用例标题" :disabled="insertSaving" />
      </el-form-item>
      <el-form-item label="前置条件">
        <el-input v-model="insertForm.precondition" placeholder="前置条件（可选）" :disabled="insertSaving" />
      </el-form-item>
      <el-form-item label="测试步骤">
        <el-input v-model="insertForm.steps" type="textarea" :rows="4" placeholder="每行一步" :disabled="insertSaving" />
      </el-form-item>
      <el-form-item label="预期结果">
        <el-input v-model="insertForm.expected_result" type="textarea" :rows="3" placeholder="预期结果" :disabled="insertSaving" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="insertDialogVisible = false" :disabled="insertSaving">取消</el-button>
      <el-button type="primary" @click="saveInsert" :loading="insertSaving">插入</el-button>
    </template>
  </el-dialog>
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
/* 行间插入位：默认极细一条空隙，hover 才亮起"+ 在此处插入用例"，不打扰阅读 */
.insert-slot { display: flex; align-items: center; gap: 8px; height: 8px; cursor: pointer; opacity: 0; transition: opacity 0.15s ease, height 0.15s ease; user-select: none; }
.insert-slot:hover { opacity: 1; height: 24px; }
.insert-line { flex: 1; height: 1px; background: #409EFF; }
.insert-btn { font-size: 12px; color: #409EFF; white-space: nowrap; }
</style>
