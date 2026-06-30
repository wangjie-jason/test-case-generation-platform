<script setup lang="ts">
import { ref, computed } from 'vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import { ElMessage, ElMessageBox } from 'element-plus'
import StateMachineForm from './StateMachineForm.vue'

const props = defineProps<{ kbId: string }>()
const store = useKnowledgeStore()
const items = computed(() => store.stateMachines)

const dialogVisible = ref(false)
const editingItem = ref<any>(null)

function openCreate() { editingItem.value = null; dialogVisible.value = true }
function openEdit(item: any) { editingItem.value = { ...item }; dialogVisible.value = true }

async function handleSubmit(data: any) {
  try {
    if (editingItem.value) {
      await store.updateStateMachine(props.kbId, editingItem.value.id, data)
    } else {
      await store.createStateMachine(props.kbId, data)
    }
    dialogVisible.value = false
    ElMessage.success(editingItem.value ? '更新成功' : '创建成功')
  } catch (e: any) { ElMessage.error(e.message) }
}

async function handleDelete(id: string) {
  try {
    await ElMessageBox.confirm('确定删除？', '提示', { type: 'warning' })
    await store.deleteStateMachine(props.kbId, id)
    ElMessage.success('删除成功')
  } catch { /* 已取消 */ }
}
</script>

<template>
  <div>
    <div style="margin-bottom: 12px"><el-button @click="openCreate">+ 添加状态流转</el-button></div>
    <el-table :data="items" border stripe>
      <el-table-column prop="entity" label="实体" />
      <el-table-column prop="from_state" label="源状态" />
      <el-table-column label="箭头" width="60" align="center"><template #default>&rarr;</template></el-table-column>
      <el-table-column prop="to_state" label="目标状态" />
      <el-table-column prop="condition" label="条件" />
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="handleDelete(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editingItem ? '编辑状态流转' : '添加状态流转'" width="560px">
      <StateMachineForm :initial="editingItem" @submit="handleSubmit" @cancel="dialogVisible = false" />
    </el-dialog>
  </div>
</template>
