<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowRight } from '@element-plus/icons-vue'
import { generationApi, type CaseRecord } from '@/api/generation'
import { formatTokens } from '@/utils/formatTokens'
import { priorityTagType } from '@/utils/priority'
import { useBatchList } from '@/composables/useBatchList'

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

// 全角开括号（【（「等）的墨迹在字框内偏右，盒子左边界虽与「前置：」对齐，
// 视觉上却像缩进了几像素。对这类开头的标题补一点负偏移抵掉。
// 本想用 hanging-punctuation，但只有 Safari 支持。
const LEADING_BRACKETS = /^[【（〔［｛「『《〈]/
function hangsPunctuation(title?: string) {
  return LEADING_BRACKETS.test(title || '')
}

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
const editForm = ref<{ id: string; batch_id: string; title: string; priority: string; precondition: string; steps: string; expected_result: string }>({
  id: '', batch_id: '', title: '', priority: '', precondition: '', steps: '', expected_result: '',
})

function openEditDialog(c: CaseRecord, bid: string) {
  editForm.value = {
    id: c.id,
    batch_id: bid,
    title: c.title || '',
    priority: c.priority || '',
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
      priority: editForm.value.priority || null,
      precondition: editForm.value.precondition,
      steps: editForm.value.steps,
      expected_result: editForm.value.expected_result,
    })
    const items = batchItems.value[editForm.value.batch_id]
    const c = items?.find(x => x.id === editForm.value.id)
    if (c) {
      c.title = updated.title
      c.priority = updated.priority
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
// 后端把新用例的 created_at 取为前后两条 created_at 的中点（列表按 created_at 升序，
// 所以时间戳就是位置），前端只负责传前后两条 case 的 id 作为锚点。
// 保存后新 case 直接插入到列表对应位置，batch 汇总的 total/reviewed/approved 各 +1
// （手动插入的默认 approved，无需再审）。
const insertDialogVisible = ref(false)
const insertSaving = ref(false)
const insertForm = ref<{ batch_id: string; prev_case_id: string | null; next_case_id: string | null; insertAt: number; title: string; priority: string; precondition: string; steps: string; expected_result: string }>({
  batch_id: '', prev_case_id: null, next_case_id: null, insertAt: 0,
  title: '', priority: '', precondition: '', steps: '', expected_result: '',
})

// insertAt 是要插入到本地 items 数组的目标下标：0=最开头，items.length=最末尾
function openInsertDialog(bid: string, insertAt: number) {
  const items = batchItems.value[bid] || []
  insertForm.value = {
    batch_id: bid,
    prev_case_id: insertAt > 0 ? items[insertAt - 1].id : null,
    next_case_id: insertAt < items.length ? items[insertAt].id : null,
    insertAt,
    title: '', priority: '', precondition: '', steps: '', expected_result: '',
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
      priority: insertForm.value.priority || null,
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
      <!-- el-statistic 只有 title/prefix/suffix 三个 slot，没有 default——
           原来写 #default 会被整个丢弃，又没传 value，于是恒显示 0 -->
      <el-statistic title="可用率" :value="usabilityRate"
                    :value-style="{ color: usabilityRate >= 85 ? '#67C23A' : '#E6A23C' }">
        <template #suffix><span :style="{color: usabilityRate >= 85 ? '#67C23A' : '#E6A23C'}">%</span></template>
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

    <div v-for="batch in displayBatches" :key="batch.batch_id" class="batch-card" :class="{ 'is-open': expandedBatch[batch.batch_id] }">
      <!-- 标题行本身就是折叠头：箭头指示展开态，不再另起一行「展开 N 条用例」 -->
      <div class="batch-header" @click="toggleBatch(batch.batch_id)">
        <el-icon class="batch-arrow"><ArrowRight /></el-icon>
        <div class="batch-title-block">
          <!-- 需求文本截断到 60 字，被切掉的部分靠 tooltip 补全（只在真截断时挂） -->
          <el-tooltip :disabled="(batch.req_text?.length || 0) <= 60" :content="batch.req_text" placement="top-start" :show-after="300" popper-class="batch-req-tip">
            <strong class="batch-name">{{ batch.req_text?.slice(0, 60) || '未命名需求' }}{{ (batch.req_text?.length || 0) > 60 ? '…' : '' }}</strong>
          </el-tooltip>
          <!-- 非「全部」tab 下显示「筛后 / 总数」，让人知道这批被筛掉了多少 -->
          <span class="batch-meta-info">
            <template v-if="filterTab === 'all'">{{ batch.total }} 条</template>
            <template v-else>{{ batch.visibleTotal }} / {{ batch.total }} 条</template>
            · {{ batch.created_at?.slice(0, 16) }}
            <!-- 该批的 token 消耗。用量统计上线前的批次没有流水，tokens 为 null 时
                 整段不显示——显示「0 tokens」会被读成「这批没花钱」，是错的。 -->
            <template v-if="batch.tokens != null"> · 消耗 {{ formatTokens(batch.tokens) }} tokens</template>
          </span>
        </div>
        <!-- 操作区在折叠头内部，点按钮不应连带折叠 -->
        <div class="batch-actions" @click.stop>
          <!-- 审核进度：细条 + 数字，扫一眼就知道哪批还没审完 -->
          <div class="batch-progress">
            <span class="bp-text">已审核 {{ batch.reviewed }}/{{ batch.total }}</span>
            <span class="bp-track">
              <span class="bp-fill" :class="{ done: batch.total > 0 && batch.reviewed >= batch.total }"
                    :style="{ width: (batch.total > 0 ? Math.round(batch.reviewed / batch.total * 100) : 0) + '%' }"></span>
            </span>
          </div>
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

      <el-collapse-transition>
      <div class="batch-body" v-show="expandedBatch[batch.batch_id]">
        <!-- 骨架屏而非一行文字：加载态得有接近真实列表的高度，
             否则展开动画从 0 长到一行、再瞬间跳到全列表，看着像"蹦"一下 -->
        <div v-if="batch.loading" class="batch-loading">
          <div class="sk-row" v-for="n in 3" :key="n">
            <el-skeleton animated>
              <template #template>
                <el-skeleton-item variant="text" style="width:52%;height:14px" />
                <div style="margin-top:8px">
                  <el-skeleton-item variant="text" style="width:34%;height:12px" />
                </div>
                <div style="margin-top:6px">
                  <el-skeleton-item variant="text" style="width:62%;height:12px" />
                </div>
              </template>
            </el-skeleton>
          </div>
        </div>
        <div v-else-if="!batch.items.length" class="batch-placeholder">
          {{ batch.loaded ? '当前筛选下无匹配用例' : '暂无数据' }}
        </div>
        <!-- 用例列表在批次内部独立滚动（max-height 60vh），批次多时不必整页下滑 -->
        <div v-else class="case-scroll">
          <!-- 首个用例前的插入位 -->
          <div class="insert-slot" v-if="filterTab === 'all'" @click="openInsertDialog(batch.batch_id, 0)">
            <span class="insert-line"></span><span class="insert-btn">+ 在此处插入用例</span><span class="insert-line"></span>
          </div>
          <template v-for="(c, idx) in batch.items" :key="c.id">
            <div class="review-item" :class="{ approved: c.review?.status === 'approved', rejected: c.review?.status === 'rejected' }">
              <div class="ri-header">
                <span class="ri-title" :class="{ hang: hangsPunctuation(c.title) }">{{ c.title }}</span>
                <!-- 间距一律交给 .ri-header 的 gap，标签/按钮上不再挂内联 margin，
                     否则两套间距叠加，每个缝隙宽度都不一样 -->
                <el-tag v-if="c.priority" size="small" :type="priorityTagType(c.priority)" effect="plain">{{ c.priority }}</el-tag>
                <el-tag v-if="c.edited" size="small" type="warning" effect="plain">已编辑</el-tag>
                <el-tag v-if="c.origin === 'supplement'" size="small" type="primary" effect="plain">补充</el-tag>
                <el-tag v-if="c.source === 'manual'" size="small" type="info" effect="plain">手动</el-tag>
                <el-tag v-if="c.review?.status === 'approved'" type="success" size="small">✓</el-tag>
                <el-tag v-else-if="c.review?.status === 'rejected'" type="danger" size="small">✗ {{ rejectReasons.find(r => r.value === c.review?.reject_reason)?.label || '' }}</el-tag>
                <template v-else>
                  <el-button size="small" type="success" @click="approveCase(c.id, batch.batch_id)">通过</el-button>
                  <el-button size="small" @click="openEditDialog(c, batch.batch_id)">编辑</el-button>
                  <el-popover placement="bottom" :width="200" trigger="click">
                    <template #reference>
                      <el-button size="small" type="danger">不可用</el-button>
                    </template>
                    <el-button v-for="r in rejectReasons" :key="r.value" size="small" style="margin:2px" @click="rejectCase(c.id, batch.batch_id, r.value)">{{ r.label }}</el-button>
                  </el-popover>
                </template>
                <!-- 已通过或已拒绝的用例也允许编辑；编辑不改 review 状态，只改内容 -->
                <el-button v-if="c.review" size="small" text @click="openEditDialog(c, batch.batch_id)">编辑</el-button>
              </div>
              <div class="ri-body">
                <div v-if="c.precondition" class="ri-line">前置：{{ c.precondition }}</div>
                <div v-if="c.steps" class="ri-line" style="white-space:pre-wrap">步骤：{{ typeof c.steps === 'string' ? c.steps : JSON.stringify(c.steps) }}</div>
                <div v-if="c.expected_result" class="ri-line">预期：{{ c.expected_result }}</div>
              </div>
            </div>
            <!-- 每条 case 之后的插入位；筛选 tab 下隐藏（否则插入位置会错位） -->
            <div class="insert-slot" v-if="filterTab === 'all'" @click="openInsertDialog(batch.batch_id, idx + 1)">
              <span class="insert-line"></span><span class="insert-btn">+ 在此处插入用例</span><span class="insert-line"></span>
            </div>
          </template>
        </div>
      </div>
      </el-collapse-transition>
    </div>
  </div>

  <!-- 编辑用例弹窗 -->
  <el-dialog v-model="editDialogVisible" title="编辑用例" width="600px" :close-on-click-modal="false">
    <el-form label-position="top" size="small">
      <el-form-item label="标题">
        <el-input v-model="editForm.title" placeholder="用例标题" :disabled="editSaving" />
      </el-form-item>
      <el-form-item label="等级">
        <el-select v-model="editForm.priority" placeholder="选择等级（可留空）" clearable :disabled="editSaving" style="width:180px">
          <el-option label="P0 核心" value="P0" />
          <el-option label="P1 重要" value="P1" />
          <el-option label="P2 边缘" value="P2" />
        </el-select>
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
      <el-form-item label="等级">
        <el-select v-model="insertForm.priority" placeholder="选择等级（可留空）" clearable :disabled="insertSaving" style="width:180px">
          <el-option label="P0 核心" value="P0" />
          <el-option label="P1 重要" value="P1" />
          <el-option label="P2 边缘" value="P2" />
        </el-select>
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
/* 批次卡片：padding 归零，交给 header / body 各自控制，展开时 header 才出下边框。
   --gutter 是卡片左内边距，--indent 是「箭头 + 间距」的宽度，
   批次标题与用例标题都从 gutter+indent 起，两者共享同一条左边界。 */
.batch-card {
  --gutter: 14px; --indent: 23px;
  border: 1px solid #e4e7ed; border-radius: 8px; margin-bottom: 16px; background: #fff; overflow: hidden;
}
/* 标题行 = 折叠头：整行可点，hover 浅蓝底，箭头指示展开态 */
.batch-header {
  display: flex; align-items: center; gap: 10px;
  padding: 12px var(--gutter); cursor: pointer; user-select: none;
  transition: background 0.2s ease;
}
.batch-header:hover { background: #f5f9ff; }
.batch-card.is-open .batch-header { border-bottom: 1px solid #ebeef5; }
/* 13px 图标 + 10px gap = 23px，与 --indent 一致 */
.batch-arrow { font-size: 13px; width: 13px; color: #a8abb2; flex-shrink: 0; transition: transform 0.2s ease, color 0.2s ease; }
.batch-header:hover .batch-arrow { color: #409EFF; }
.batch-card.is-open .batch-arrow { transform: rotate(90deg); color: #409EFF; }
.batch-title-block { flex: 1; min-width: 0; }
.batch-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; white-space: nowrap; }
/* 同上：清掉 Element Plus 的相邻按钮 margin，缝隙只由 gap 决定 */
.batch-actions :deep(.el-button + .el-button) { margin-left: 0; }
.batch-name { font-size: 14px; font-weight: 600; line-height: 1.4; color: #303133; display: block; }
.batch-meta-info { display: block; font-size: 12px; color: #a8abb2; margin-top: 3px; }
/* 审核进度：数字下面压一条 3px 细条，比纯数字更快扫出哪批没审完 */
.batch-progress { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; margin-right: 4px; }
.bp-text { font-size: 12px; color: #909399; line-height: 1; }
.bp-track { display: block; width: 72px; height: 3px; border-radius: 2px; background: #ebeef5; overflow: hidden; }
.bp-fill { display: block; height: 100%; border-radius: 2px; background: #409EFF; transition: width 0.3s ease; }
.bp-fill.done { background: #67C23A; }
/* 展开后的用例列表：左内边距对齐到批次标题的左边界，使「用例标题」与上方
   「批次标题」共用一条左缘。
   滚动放在内层 .case-scroll 而不是 .batch-body：collapse-transition 靠动画
   height 实现，跟 max-height 会互相钳制，展开动画会跳。 */
.batch-body { padding: 0 var(--gutter) 6px; }
/* 加载骨架：三行占位，行距与 .review-item 一致，撑出接近真实列表的高度 */
.batch-loading { padding: 0; }
.sk-row { padding: 10px 0 10px var(--indent); border-bottom: 1px solid #f0f0f0; }
.sk-row:last-child { border-bottom: none; }
.batch-placeholder { text-align: center; padding: 18px; font-size: 13px; color: #909399; }
.case-scroll { max-height: 60vh; overflow-y: auto; overscroll-behavior: contain; }
.review-item { padding: 10px 0 10px var(--indent); border-bottom: 1px solid #f0f0f0; }
.review-item:last-child { border-bottom: none; }
/* 状态底色留出左右内边距、不通到卡片边缘，读起来是这一行的高亮而非整块色带 */
.review-item.approved, .review-item.rejected { border-radius: 4px; padding-right: 8px; }
.review-item.approved { background: #f0f9eb; }
.review-item.rejected { background: #fef0f0; }
.ri-header { display: flex; align-items: center; gap: 8px; }
/* Element Plus 给相邻按钮加了 margin-left:12px，会与上面的 gap 叠加成不等宽缝隙 */
.ri-header :deep(.el-button + .el-button) { margin-left: 0; }
.ri-title { font-size: 13px; font-weight: 600; flex: 1; }
/* 全角开括号墨迹偏右，补负偏移让它的视觉左缘与「前置：」「步骤：」及批次标题对齐 */
.ri-title.hang { margin-left: -3px; }
.ri-body { margin-top: 4px; }
.ri-line { font-size: 12px; color: #909399; }
/* 行间插入位：默认极细一条空隙，hover 才亮起"+ 在此处插入用例"，不打扰阅读 */
.insert-slot { display: flex; align-items: center; gap: 8px; height: 8px; cursor: pointer; opacity: 0; transition: opacity 0.15s ease, height 0.15s ease; user-select: none; }
.insert-slot:hover { opacity: 1; height: 24px; }
.insert-line { flex: 1; height: 1px; background: #409EFF; }
.insert-btn { font-size: 12px; color: #409EFF; white-space: nowrap; }
</style>

<!-- tooltip 弹层 teleport 到 body，scoped 选择器管不到，故单开一个非 scoped 块 -->
<style>
.batch-req-tip { max-width: 420px; line-height: 1.6; }
</style>
