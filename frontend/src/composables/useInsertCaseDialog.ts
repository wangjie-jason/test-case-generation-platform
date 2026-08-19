import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { generationApi, type CaseRecord, type BatchSummary } from '@/api/generation'
import type { Ref } from 'vue'

interface InsertForm {
  batch_id: string
  prev_case_id: string | null
  next_case_id: string | null
  insertAt: number
  title: string
  priority: string
  precondition: string
  steps: string
  expected_result: string
}

/**
 * 手动插入用例弹窗的状态 + 保存逻辑。
 *
 * 场景：AI 漏了整个模块/功能，用户想在两条 case 之间补一条。
 * 后端把新用例的 created_at 取为前后两条 created_at 的中点（列表按 created_at 升序，
 * 所以时间戳就是位置），前端只负责传前后两条 case 的 id 作为锚点。
 * 保存后新 case 直接插入到列表对应位置，batch 汇总的 total/reviewed/approved 各 +1
 * （手动插入的默认 approved，无需再审）。
 */
export function useInsertCaseDialog(
  batches: Ref<BatchSummary[]>,
  batchItems: Ref<Record<string, CaseRecord[]>>,
) {
  const dialogVisible = ref(false)
  const saving = ref(false)
  const form = ref<InsertForm>({
    batch_id: '', prev_case_id: null, next_case_id: null, insertAt: 0,
    title: '', priority: '', precondition: '', steps: '', expected_result: '',
  })

  // insertAt 是要插入到本地 items 数组的目标下标：0=最开头，items.length=最末尾
  function open(bid: string, insertAt: number) {
    const items = batchItems.value[bid] || []
    form.value = {
      batch_id: bid,
      prev_case_id: insertAt > 0 ? items[insertAt - 1].id : null,
      next_case_id: insertAt < items.length ? items[insertAt].id : null,
      insertAt,
      title: '', priority: '', precondition: '', steps: '', expected_result: '',
    }
    dialogVisible.value = true
  }

  async function save() {
    if (!form.value.title.trim()) {
      ElMessage.warning('标题不能为空')
      return
    }
    saving.value = true
    try {
      const created = await generationApi.createCase({
        batch_id: form.value.batch_id,
        prev_case_id: form.value.prev_case_id,
        next_case_id: form.value.next_case_id,
        title: form.value.title,
        priority: form.value.priority || null,
        precondition: form.value.precondition,
        steps: form.value.steps,
        expected_result: form.value.expected_result,
      })
      const items = batchItems.value[form.value.batch_id]
      if (items) {
        items.splice(form.value.insertAt, 0, created)
      }
      // 手动插入的 case 后端直接 approved，同步 batch 汇总
      const b = batches.value.find(x => x.batch_id === form.value.batch_id)
      if (b) { b.total += 1; b.reviewed += 1; b.approved += 1 }
      ElMessage.success('已插入用例')
      dialogVisible.value = false
    } catch (e: any) {
      ElMessage.error(e?.message || '插入失败')
    } finally {
      saving.value = false
    }
  }

  return { dialogVisible, saving, form, open, save }
}
