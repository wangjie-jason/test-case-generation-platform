import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { generationApi, type CaseRecord } from '@/api/generation'
import type { Ref } from 'vue'

interface EditForm {
  id: string
  batch_id: string
  title: string
  priority: string
  precondition: string
  steps: string
  expected_result: string
}

/**
 * 用例编辑弹窗的状态 + 保存逻辑。
 *
 * 场景：有些生成结果只是文案上差几个字，直接拒绝可惜。允许四字段一起改。
 * 产品口径：编辑 = AI 一次没产出合格结果，仍算「不通过」，只是拒绝原因记为 edited，
 * 不污染 AI 可用率。可用率始终反映 AI 一次到位的能力。
 */
export function useEditCaseDialog(batchItems: Ref<Record<string, CaseRecord[]>>) {
  const dialogVisible = ref(false)
  const saving = ref(false)
  const form = ref<EditForm>({
    id: '', batch_id: '', title: '', priority: '',
    precondition: '', steps: '', expected_result: '',
  })

  function open(c: CaseRecord, bid: string) {
    form.value = {
      id: c.id,
      batch_id: bid,
      title: c.title || '',
      priority: c.priority || '',
      precondition: c.precondition || '',
      // steps 可能是数组（老的 GeneratedTestCase 结构）或字符串，统一转成字符串给 textarea 用
      steps: Array.isArray(c.steps) ? (c.steps as unknown[]).map(String).join('\n') : (c.steps || ''),
      expected_result: c.expected_result || '',
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
      const updated = await generationApi.updateCase(form.value.id, {
        title: form.value.title,
        priority: form.value.priority || null,
        precondition: form.value.precondition,
        steps: form.value.steps,
        expected_result: form.value.expected_result,
      })
      const items = batchItems.value[form.value.batch_id]
      const c = items?.find(x => x.id === form.value.id)
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
      dialogVisible.value = false
    } catch (e: any) {
      ElMessage.error(e?.message || '保存失败')
    } finally {
      saving.value = false
    }
  }

  return { dialogVisible, saving, form, open, save }
}
