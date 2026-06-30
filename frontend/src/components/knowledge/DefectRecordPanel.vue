<script setup lang="ts">
import { ref, computed } from 'vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import { defectRecordApi } from '@/api/knowledge'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { DefectRecord } from '@/types/knowledge'

type DefectSeverity = NonNullable<DefectRecord['severity']>
type DefectForm = Pick<DefectRecord, 'title' | 'root_cause' | 'description' | 'related_case' | 'occurred_at'> & { severity: DefectSeverity }

const props = defineProps<{ kbId: string }>()
const store = useKnowledgeStore()
const items = computed(() => store.defectRecords)
const emptyForm = (): DefectForm => ({ title: '', severity: 'minor', root_cause: '', description: '', related_case: '', occurred_at: '' })
const dialogVisible = ref(false); const editingItem = ref<any>(null)
const form = ref<DefectForm>(emptyForm())
function openCreate() { editingItem.value = null; form.value = emptyForm(); dialogVisible.value = true }
function openEdit(item: any) { editingItem.value = { ...item }; Object.assign(form.value, item); dialogVisible.value = true }
async function handleSubmit() {
  try {
    if (editingItem.value) await store.updateDefect(props.kbId, editingItem.value.id, form.value)
    else await store.createDefect(props.kbId, form.value)
    dialogVisible.value = false; ElMessage.success(editingItem.value ? '更新成功' : '创建成功')
  } catch (e: any) { ElMessage.error(e.message) }
}
async function handleDelete(id: string) { try { await ElMessageBox.confirm('确定删除？', '提示', { type: 'warning' }); await store.deleteDefect(props.kbId, id); ElMessage.success('删除成功') } catch {} }
async function handleImport(options: any) { try { const r = await defectRecordApi.importExcel(props.kbId, options.file); ElMessage.success(`导入 ${r.imported} 条`); store._fetch(props.kbId) } catch (e: any) { ElMessage.error(e.message) } }
const sev = (s: string) => ({ critical: 'danger', major: 'warning', minor: 'info', trivial: '' } as any)[s] || ''
const sevLabel = (s: string) => ({ critical: '致命', major: '严重', minor: '一般', trivial: '轻微' } as any)[s] || s
</script>
<template>
  <div>
    <div style="margin-bottom:12px;display:flex;gap:8px">
      <el-button @click="openCreate">+ 添加缺陷</el-button>
      <el-upload :auto-upload="true" :show-file-list="false" :http-request="handleImport" accept=".xlsx,.xls" style="display:inline-block"><el-button plain>导入 Excel</el-button></el-upload>
    </div>
    <el-table :data="items" border stripe>
      <el-table-column prop="title" label="标题" min-width="180" />
      <el-table-column label="级别" width="70"><template #default="{ row }"><el-tag :type="sev(row.severity)" size="small">{{ sevLabel(row.severity) }}</el-tag></template></el-table-column>
      <el-table-column prop="root_cause" label="根因" width="100" />
      <el-table-column label="描述" min-width="280"><template #default="{ row }"><div style="max-height:40px;overflow:hidden;font-size:12px">{{ row.description.slice(0, 150) }}</div></template></el-table-column>
      <el-table-column label="操作" width="140"><template #default="{ row }"><el-button link type="primary" @click="openEdit(row)">编辑</el-button><el-button link type="danger" @click="handleDelete(row.id)">删除</el-button></template></el-table-column>
    </el-table>
    <el-empty v-if="!items.length" description="暂无缺陷" />
    <el-dialog v-model="dialogVisible" :title="editingItem ? '编辑缺陷' : '添加缺陷'" width="560px">
      <el-form @submit.prevent="handleSubmit" label-width="80px">
        <el-form-item label="标题" required><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="级别"><el-select v-model="form.severity"><el-option label="致命" value="critical" /><el-option label="严重" value="major" /><el-option label="一般" value="minor" /><el-option label="轻微" value="trivial" /></el-select></el-form-item>
        <el-form-item label="根因"><el-input v-model="form.root_cause" /></el-form-item>
        <el-form-item label="描述" required><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="关联用例"><el-input v-model="form.related_case" /></el-form-item>
        <el-form-item label="发生时间"><el-input v-model="form.occurred_at" /></el-form-item>
        <el-form-item><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="handleSubmit">确定</el-button></el-form-item>
      </el-form>
    </el-dialog>
  </div>
</template>
