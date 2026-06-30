<script setup lang="ts">
import { ref, computed } from 'vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import { ElMessage, ElMessageBox } from 'element-plus'
import TermMappingForm from './TermMappingForm.vue'

const props = defineProps<{ kbId: string }>()
const store = useKnowledgeStore()
const items = computed(() => store.termMappings)

const dialogVisible = ref(false)
const editingItem = ref<any>(null)

function openCreate() { editingItem.value = null; dialogVisible.value = true }
function openEdit(item: any) { editingItem.value = { ...item }; dialogVisible.value = true }

async function handleSubmit(data: any) {
  try {
    if (editingItem.value) {
      await store.updateTermMapping(props.kbId, editingItem.value.id, data)
    } else {
      await store.createTermMapping(props.kbId, data)
    }
    dialogVisible.value = false
    ElMessage.success(editingItem.value ? '更新成功' : '创建成功')
  } catch (e: any) { ElMessage.error(e.message) }
}

async function handleDelete(id: string) {
  try {
    await ElMessageBox.confirm('确定删除？', '提示', { type: 'warning' })
    await store.deleteTermMapping(props.kbId, id)
    ElMessage.success('删除成功')
  } catch { /* 已取消 */ }
}
</script>

<template>
  <div>
    <div style="margin-bottom: 12px"><el-button @click="openCreate">+ 添加映射</el-button></div>
    <el-table :data="items" border stripe>
      <el-table-column prop="ui_term" label="页面术语" />
      <el-table-column label="映射" width="60" align="center"><template #default>&harr;</template></el-table-column>
      <el-table-column prop="tech_field" label="技术字段" />
      <el-table-column prop="mapping_desc" label="映射说明" />
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="handleDelete(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editingItem ? '编辑映射' : '添加映射'" width="560px">
      <TermMappingForm :initial="editingItem" @submit="handleSubmit" @cancel="dialogVisible = false" />
    </el-dialog>
  </div>
</template>
