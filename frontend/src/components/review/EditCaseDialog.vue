<script setup lang="ts">
interface EditForm {
  id: string
  batch_id: string
  title: string
  priority: string
  precondition: string
  steps: string
  expected_result: string
}

const props = defineProps<{
  visible: boolean
  saving: boolean
  form: EditForm
}>()

const emit = defineEmits<{
  (e: 'update:visible', v: boolean): void
  (e: 'update:form', f: EditForm): void
  (e: 'save'): void
  (e: 'cancel'): void
}>()

function setVisible(v: boolean) { emit('update:visible', v) }
function updateField<K extends keyof EditForm>(key: K, value: EditForm[K]) {
  emit('update:form', { ...props.form, [key]: value })
}
</script>

<template>
  <el-dialog :model-value="visible" @update:model-value="setVisible"
             title="编辑用例" width="600px" :close-on-click-modal="false">
    <el-form label-position="top" size="small">
      <el-form-item label="标题">
        <el-input :model-value="form.title"
                  @update:model-value="(v: string) => updateField('title', v)"
                  placeholder="用例标题" :disabled="saving" />
      </el-form-item>
      <el-form-item label="等级">
        <el-select :model-value="form.priority"
                   @update:model-value="(v: string) => updateField('priority', v)"
                   placeholder="选择等级（可留空）" clearable :disabled="saving" style="width:180px">
          <el-option label="P0 核心" value="P0" />
          <el-option label="P1 重要" value="P1" />
          <el-option label="P2 边缘" value="P2" />
        </el-select>
      </el-form-item>
      <el-form-item label="前置条件">
        <el-input :model-value="form.precondition"
                  @update:model-value="(v: string) => updateField('precondition', v)"
                  placeholder="前置条件（可选）" :disabled="saving" />
      </el-form-item>
      <el-form-item label="测试步骤">
        <el-input :model-value="form.steps"
                  @update:model-value="(v: string) => updateField('steps', v)"
                  type="textarea" :rows="4" placeholder="每行一步" :disabled="saving" />
      </el-form-item>
      <el-form-item label="预期结果">
        <el-input :model-value="form.expected_result"
                  @update:model-value="(v: string) => updateField('expected_result', v)"
                  type="textarea" :rows="3" placeholder="预期结果" :disabled="saving" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('cancel')" :disabled="saving">取消</el-button>
      <el-button type="primary" @click="emit('save')" :loading="saving">保存</el-button>
    </template>
  </el-dialog>
</template>
