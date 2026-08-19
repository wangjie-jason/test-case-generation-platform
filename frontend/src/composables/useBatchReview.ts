import { ElMessage } from 'element-plus'
import { generationApi, type CaseRecord, type BatchSummary } from '@/api/generation'
import type { Ref } from 'vue'

/**
 * 审核批次的本地状态管理：单条 / 批量 通过或拒绝 + 同步 batch 汇总。
 *
 * 所有改动只动 store 里的 batches / batchItems，不重新拉后端——审核页面 200ms 内
 * 就能给出视觉反馈，比一次完整 reload 体感好得多。bumpBatchStats 负责本地推平
 * reviewed/approved 计数，避免对账错位。
 */
export function useBatchReview(
  batches: Ref<BatchSummary[]>,
  batchItems: Ref<Record<string, CaseRecord[]>>,
) {
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

  return { approveCase, rejectCase, approveAllInBatch, rejectAllInBatch }
}
