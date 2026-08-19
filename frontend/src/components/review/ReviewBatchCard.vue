<script setup lang="ts">
import { ArrowRight } from '@element-plus/icons-vue'
import { formatTokens } from '@/utils/formatTokens'
import ReviewCaseItem from './ReviewCaseItem.vue'

interface ReviewRejectReason {
  value: string
  label: string
}

defineProps<{
  batch: any
  rejectReasons: ReviewRejectReason[]
  hangsPunctuation: (title?: string) => boolean
  showInsertSlot: boolean  // 筛选 tab 下隐藏插入位（位置会错位）
}>()

const emit = defineEmits<{
  (e: 'toggle', batchId: string): void
  (e: 'approveAll', batchId: string, items: any[]): void
  (e: 'rejectAll', batchId: string, items: any[], reason: string): void
  (e: 'approve', caseId: string, batchId: string): void
  (e: 'reject', caseId: string, batchId: string, reason: string): void
  (e: 'edit', c: any, batchId: string): void
  (e: 'insertAfter', batchId: string, insertAt: number, c: any): void
}>()
</script>

<template>
  <div class="batch-card" :class="{ 'is-open': batch.expanded }">
    <!-- 标题行本身就是折叠头：箭头指示展开态，不再另起一行「展开 N 条用例」 -->
    <div class="batch-header" @click="emit('toggle', batch.batch_id)">
      <el-icon class="batch-arrow"><ArrowRight /></el-icon>
      <div class="batch-title-block">
        <!-- 需求文本截断到 60 字，被切掉的部分靠 tooltip 补全（只在真截断时挂） -->
        <el-tooltip :disabled="(batch.req_text?.length || 0) <= 60" :content="batch.req_text" placement="top-start" :show-after="300" popper-class="batch-req-tip">
          <strong class="batch-name">{{ batch.req_text?.slice(0, 60) || '未命名需求' }}{{ (batch.req_text?.length || 0) > 60 ? '…' : '' }}</strong>
        </el-tooltip>
        <!-- 非「全部」tab 下显示「筛后 / 总数」，让人知道这批被筛掉了多少 -->
        <span class="batch-meta-info">
          <template v-if="batch.visibleTotal === batch.total">{{ batch.total }} 条</template>
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
        <el-button size="small" type="success" :disabled="!batch.loaded" @click="emit('approveAll', batch.batch_id, batch.items)">全部通过</el-button>
        <el-popover placement="bottom" :width="220" trigger="click" :disabled="!batch.loaded">
          <template #reference>
            <el-button size="small" type="danger" :disabled="!batch.loaded">全部拒绝</el-button>
          </template>
          <div style="font-size:13px;margin-bottom:8px">选择拒绝原因：</div>
          <el-button v-for="r in rejectReasons" :key="r.value" size="small" style="margin:2px" @click="emit('rejectAll', batch.batch_id, batch.items, r.value)">{{ r.label }}</el-button>
        </el-popover>
      </div>
    </div>

    <el-collapse-transition>
      <div class="batch-body" v-show="batch.expanded">
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
          <template v-for="(c, idx) in batch.items" :key="c.id">
            <ReviewCaseItem
              :c="c"
              :batch-id="batch.batch_id"
              :reject-reasons="rejectReasons"
              :hangs-punctuation="hangsPunctuation"
              @approve="(caseId, bid) => emit('approve', caseId, bid)"
              @reject="(caseId, bid, reason) => emit('reject', caseId, bid, reason)"
              @edit="(cc, bid) => emit('edit', cc, bid)"
              @insertAfter="(bid, insertAt) => emit('insertAfter', bid, insertAt, c)"
            />
            <!-- 每条 case 之后的插入位；筛选 tab 下隐藏（否则插入位置会错位） -->
            <div class="insert-slot" v-if="showInsertSlot" @click="emit('insertAfter', batch.batch_id, idx + 1, c)">
              <span class="insert-line"></span><span class="insert-btn">+ 在此处插入用例</span><span class="insert-line"></span>
            </div>
          </template>
        </div>
      </div>
    </el-collapse-transition>
  </div>
</template>

<style scoped>
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
