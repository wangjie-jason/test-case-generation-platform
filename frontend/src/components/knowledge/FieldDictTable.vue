<script setup lang="ts">
import { ref, computed } from 'vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import { ElMessage, ElMessageBox } from 'element-plus'
import FieldDictForm from './FieldDictForm.vue'

const props = defineProps<{ kbId: string }>()
const store = useKnowledgeStore()
const items = computed(() => store.fieldDicts)

const dialogVisible = ref(false)
const editingItem = ref<any>(null)

function openCreate() { editingItem.value = null; dialogVisible.value = true }
function openEdit(item: any) { editingItem.value = { ...item }; dialogVisible.value = true }

async function handleSubmit(data: any) {
  try {
    if (editingItem.value) {
      await store.updateFieldDict(props.kbId, editingItem.value.id, data)
    } else {
      await store.createFieldDict(props.kbId, data)
    }
    dialogVisible.value = false
    ElMessage.success(editingItem.value ? '更新成功' : '创建成功')
  } catch (e: any) { ElMessage.error(e.message) }
}

async function handleDelete(id: string) {
  try {
    await ElMessageBox.confirm('确定删除？', '提示', { type: 'warning' })
    await store.deleteFieldDict(props.kbId, id)
    ElMessage.success('删除成功')
  } catch { /* 已取消 */ }
}
</script>

<template>
  <div>
    <div style="margin-bottom: 12px"><el-button @click="openCreate">+ 添加字段</el-button></div>
    <el-table :data="items" border stripe>
      <el-table-column prop="field_name" label="字段名" />
      <el-table-column prop="display_name" label="页面展示名" />
      <el-table-column prop="data_type" label="类型" width="80" />
      <el-table-column prop="enum_values" label="枚举值" />
      <el-table-column prop="description" label="业务含义" />
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="handleDelete(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editingItem ? '编辑字段' : '添加字段'" width="560px">
      <FieldDictForm :initial="editingItem" @submit="handleSubmit" @cancel="dialogVisible = false" />
    </el-dialog>
  </div>
</template>
