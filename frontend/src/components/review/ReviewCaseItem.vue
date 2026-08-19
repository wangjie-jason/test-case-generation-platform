<script setup lang="ts">
import { priorityTagType } from '@/utils/priority'
import { renderSteps } from '@/utils/renderSteps'
import type { CaseRecord } from '@/api/generation'

interface ReviewRejectReason {
  value: string
  label: string
}

defineProps<{
  c: CaseRecord
  batchId: string
  rejectReasons: ReviewRejectReason[]
  /** 全角开括号（【（「等）的墨迹在字框内偏右，盒子左边界虽与「前置：」对齐，
   *  视觉上却像缩进了几像素。对这类开头的标题补一点负偏移抵掉。
   *  本想用 hanging-punctuation，但只有 Safari 支持。 */
  hangsPunctuation: (title?: string) => boolean
}>()

const emit = defineEmits<{
  (e: 'approve', caseId: string, batchId: string): void
  (e: 'reject', caseId: string, batchId: string, reason: string): void
  (e: 'edit', c: CaseRecord, batchId: string): void
}>()
</script>

<template>
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
        <el-button size="small" type="success" @click="emit('approve', c.id, batchId)">通过</el-button>
        <el-button size="small" @click="emit('edit', c, batchId)">编辑</el-button>
        <el-popover placement="bottom" :width="200" trigger="click">
          <template #reference>
            <el-button size="small" type="danger">不可用</el-button>
          </template>
          <el-button v-for="r in rejectReasons" :key="r.value" size="small" style="margin:2px" @click="emit('reject', c.id, batchId, r.value)">{{ r.label }}</el-button>
        </el-popover>
      </template>
      <!-- 已通过或已拒绝的用例也允许编辑；编辑不改 review 状态，只改内容 -->
      <el-button v-if="c.review" size="small" text @click="emit('edit', c, batchId)">编辑</el-button>
    </div>
    <div class="ri-body">
      <div v-if="c.precondition" class="ri-line">前置：{{ c.precondition }}</div>
      <div v-if="c.steps" class="ri-line" style="white-space:pre-wrap">步骤：{{ renderSteps(c.steps) }}</div>
      <div v-if="c.expected_result" class="ri-line">预期：{{ c.expected_result }}</div>
    </div>
  </div>
</template>

<style scoped>
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
</style>
