<script setup lang="ts">
import { ref, computed } from 'vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import { ElMessage, ElMessageBox } from 'element-plus'
import BusinessRuleForm from './BusinessRuleForm.vue'

const props = defineProps<{ kbId: string }>()
const store = useKnowledgeStore()
const items = computed(() => store.businessRules)

const dialogVisible = ref(false)
const editingItem = ref<any>(null)

function openCreate() { editingItem.value = null; dialogVisible.value = true }
function openEdit(item: any) { editingItem.value = { ...item }; dialogVisible.value = true }

async function handleSubmit(data: any) {
  try {
    if (editingItem.value) {
      await store.updateBusinessRule(props.kbId, editingItem.value.id, data)
    } else {
      await store.createBusinessRule(props.kbId, data)
    }
    dialogVisible.value = false
    ElMessage.success(editingItem.value ? '更新成功' : '创建成功')
  } catch (e: any) { ElMessage.error(e.message) }
}

async function handleDelete(id: string) {
  try {
    await ElMessageBox.confirm('确定删除？', '提示', { type: 'warning' })
    await store.deleteBusinessRule(props.kbId, id)
    ElMessage.success('删除成功')
  } catch { /* 已取消 */ }
}
</script>

<template>
  <div>
    <div style="margin-bottom: 12px"><el-button @click="openCreate">+ 添加规则</el-button></div>
    <el-table :data="items" border stripe>
      <el-table-column prop="rule_name" label="规则名称" />
      <el-table-column prop="rule_type" label="类型" width="80">
        <template #default="{ row }">
          <el-tag :type="row.rule_type === 'hard' ? 'danger' : 'warning'" size="small">
            {{ row.rule_type === 'hard' ? '硬规则' : '软规则' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="expression" label="表达式" />
      <el-table-column prop="source" label="来源" width="140" />
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="handleDelete(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editingItem ? '编辑规则' : '添加规则'" width="560px">
      <BusinessRuleForm :initial="editingItem" @submit="handleSubmit" @cancel="dialogVisible = false" />
    </el-dialog>
  </div>
</template>
