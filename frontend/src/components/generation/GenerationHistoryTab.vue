<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowRight } from '@element-plus/icons-vue'
import { generationApi, type BatchSummary, type CaseRecord } from '@/api/generation'
import { saveBlob } from '@/utils/saveBlob'
import { priorityTagType } from '@/utils/priority'

const props = defineProps<{
  batches: BatchSummary[]
  batchItems: Record<string, CaseRecord[]>
  loadingBatch: Record<string, boolean>
  expandedBatch: Record<string, boolean>
}>()

const emit = defineEmits<{
  (e: 'refresh'): void
  (e: 'toggle', batchId: string): void
}>()

interface BatchGroup extends BatchSummary {
  items: CaseRecord[]
  loading: boolean
}

const batchGroups = computed<BatchGroup[]>(() => props.batches.map(b => ({
  ...b,
  items: props.batchItems[b.batch_id] || [],
  loading: !!props.loadingBatch[b.batch_id],
})))

async function downloadBatch(batch: BatchSummary, scope: 'all' | 'approved' = 'all') {
  try {
    // 保证下载到的是全量：即使用户没展开也现拉一次。
    const items = props.batchItems[batch.batch_id] || await generationApi.listCases(batch.batch_id)
    // 「仅通过」只认审核动作的结论 review.status === 'approved'，与用例是否被人工
    // 编辑过（edited）无关：编辑后点了通过就能下载，没点通过就不算。
    const picked = scope === 'approved'
      ? items.filter((c: any) => c.review?.status === 'approved')
      : items
    if (!picked.length) {
      ElMessage.warning(scope === 'approved' ? '该批次暂无审核通过的用例' : '该批次没有用例')
      return
    }
    const blob = await generationApi.exportCases(picked)
    const base = batch.req_text || batch.created_at?.slice(0, 10) || 'test_cases'
    // 文件名带上范围，避免「全部」和「仅通过」两份下载下来同名难分辨。
    saveBlob(blob, `${base}${scope === 'approved' ? '_已通过' : ''}.xlsx`)
  } catch (e: any) { ElMessage.error(e.message) }
}
</script>

<template>
  <div class="history-tab">
    <el-card>
      <template #header>
        <div class="results-toolbar">
          <span>生成历史（{{ batchGroups.length }} 批次）</span>
          <el-button size="small" @click="emit('refresh')">刷新</el-button>
        </div>
      </template>
      <div v-for="b in batchGroups" :key="b.batch_id" class="batch-card" :class="{ 'is-open': expandedBatch[b.batch_id] }">
        <!-- 标题行本身就是折叠头：箭头指示展开态，不再另起一行「展开 N 条用例」 -->
        <div class="batch-header" @click="emit('toggle', b.batch_id)">
          <el-icon class="batch-arrow"><ArrowRight /></el-icon>
          <div class="batch-title-block">
            <!-- 需求文本截断到 60 字，被切掉的部分靠 tooltip 补全（只在真截断时挂） -->
            <el-tooltip :disabled="(b.req_text?.length || 0) <= 60" :content="b.req_text" placement="top-start" :show-after="300" popper-class="batch-req-tip">
              <strong class="batch-name">{{ b.req_text?.slice(0, 60) || '未命名需求' }}{{ (b.req_text?.length || 0) > 60 ? '…' : '' }}</strong>
            </el-tooltip>
            <span class="batch-meta-info">{{ b.total }} 条 · {{ b.created_at?.slice(0, 16) }}</span>
          </div>
          <!-- 下载按钮在折叠头内部，点它不应连带折叠 -->
          <div class="batch-actions" @click.stop>
            <el-dropdown split-button size="small" type="success" @click="downloadBatch(b, 'all')"
                         @command="(scope: 'all' | 'approved') => downloadBatch(b, scope)">
              下载 Excel
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="all">全部用例</el-dropdown-item>
                  <el-dropdown-item command="approved">仅通过用例</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
        <el-collapse-transition>
          <div class="batch-body" v-show="expandedBatch[b.batch_id]">
            <!-- 骨架屏而非一行文字：加载态得有接近真实列表的高度，
                 否则展开动画从 0 长到一行、再瞬间跳到全列表，看着像"蹦"一下 -->
            <div v-if="b.loading" class="batch-loading">
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
            <div v-else-if="!b.items.length" class="batch-placeholder">暂无数据</div>
            <!-- 用例列表在批次内部独立滚动（max-height 60vh），批次多时不必整页下滑 -->
            <div v-else class="case-scroll">
              <div v-for="c in b.items" :key="c.id" class="hist-item">
                <el-tag v-if="c.priority" size="small" :type="priorityTagType(c.priority)" effect="plain" style="margin-right:6px">{{ c.priority }}</el-tag>
                <el-tag v-if="c.origin === 'supplement'" size="small" type="primary" effect="plain" style="margin-right:6px">补充</el-tag>
                <strong>{{ c.title }}</strong>
                <div v-if="c.precondition" style="color:#909399">前置：{{ c.precondition }}</div>
                <div v-if="c.steps" style="color:#909399;white-space:pre-wrap">步骤：{{ typeof c.steps === 'string' ? c.steps : JSON.stringify(c.steps) }}</div>
                <div v-if="c.expected_result" style="color:#909399">预期：{{ c.expected_result }}</div>
              </div>
            </div>
          </div>
        </el-collapse-transition>
      </div>
      <el-empty v-if="!batchGroups.length" description="暂无历史" />
    </el-card>
  </div>
</template>

<style scoped>
.history-tab { max-width: 960px; margin: 0 auto; }
.results-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
/* 历史批次卡片：标题行即折叠头（整行可点 + 箭头指示）。
   --gutter 卡片左内边距，--indent 是「箭头 + 间距」宽度，
   用例标题与批次标题都从 gutter+indent 起，共享同一条左边界。 */
.batch-card {
  --gutter: 14px; --indent: 23px;
  border: 1px solid #e4e7ed; border-radius: 8px; margin-bottom: 12px; overflow: hidden;
}
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
.batch-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.batch-name { font-size: 14px; font-weight: 600; line-height: 1.4; color: #303133; display: block; }
.batch-meta-info { display: block; font-size: 12px; color: #a8abb2; margin-top: 3px; }
/* 展开后的用例列表：左内边距对齐到批次标题的左边界。
   滚动放内层：collapse-transition 动画 height，与 max-height 会互相钳制 */
.batch-body { padding: 0 var(--gutter) 6px; }
/* 加载骨架：三行占位，行距与 .hist-item 一致，撑出接近真实列表的高度 */
.batch-loading { padding: 0; }
.sk-row { padding: 10px 0 10px var(--indent); border-bottom: 1px solid #f0f0f0; }
.sk-row:last-child { border-bottom: none; }
.batch-placeholder { text-align: center; padding: 18px; font-size: 13px; color: #909399; }
.case-scroll { max-height: 60vh; overflow-y: auto; overscroll-behavior: contain; }
.hist-item { padding: 10px 0 10px var(--indent); border-bottom: 1px solid #f0f0f0; font-size: 13px; }
.hist-item:last-child { border-bottom: none; }
</style>

<!-- tooltip 弹层 teleport 到 body，scoped 选择器管不到，故单开一个非 scoped 块。
     审核页也有同名一份：路由是懒加载的，不能指望另一个页面已经把样式带进来。 -->
<style>
.batch-req-tip { max-width: 420px; line-height: 1.6; }
</style>
