<script setup lang="ts">
import { ref, type Component } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

interface Column {
  prop: string
  label: string
  width?: string | number
  align?: 'left' | 'center' | 'right'
  /** 纯展示列（如状态流转的 → 箭头）：不取 row 上的值，内容全由 #cell-xxx 插槽给 */
  display?: boolean
}

const props = defineProps<{
  items: Array<Record<string, any>>
  columns: Column[]
  formComponent: Component
  addLabel: string
  dialogLabel: string
  create: (data: Record<string, any>) => Promise<unknown>
  update: (id: string, data: Record<string, any>) => Promise<unknown>
  remove: (id: string) => Promise<unknown>
}>()

const dialogVisible = ref(false)
const editingItem = ref<Record<string, any> | null>(null)
function openCreate() { editingItem.value = null; dialogVisible.value = true }
function openEdit(item: Record<string, any>) { editingItem.value = { ...item }; dialogVisible.value = true }

async function save(data: Record<string, any>) {
  try {
    if (editingItem.value) await props.update(editingItem.value.id, data)
    else await props.create(data)
    dialogVisible.value = false
    ElMessage.success(editingItem.value ? '更新成功' : '创建成功')
  } catch (e: any) { ElMessage.error(e?.message || '保存失败') }
}

async function removeItem(id: string) {
  // 两段分开：confirm 的 reject 是「用户点了取消」，静默即可；
  // 删除接口的失败必须报出来，否则删不掉却毫无提示。
  try { await ElMessageBox.confirm('确定删除？', '提示', { type: 'warning' }) }
  catch { return }
  try {
    await props.remove(id)
    ElMessage.success('删除成功')
  } catch (e: any) { ElMessage.error(e?.message || '删除失败') }
}
</script>

<template>
  <div>
    <div style="margin-bottom:12px"><el-button @click="openCreate">+ {{ addLabel }}</el-button></div>
    <el-table :data="items" border stripe>
      <el-table-column v-for="column in columns" :key="column.prop"
                       :prop="column.display ? undefined : column.prop"
                       :label="column.label" :width="column.width" :align="column.align || 'left'">
        <template #default="{ row }"><slot :name="`cell-${column.prop}`" :row="row">{{ column.display ? '' : row[column.prop] }}</slot></template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="removeItem(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-dialog v-model="dialogVisible" :title="editingItem ? `编辑${dialogLabel}` : `添加${dialogLabel}`" width="560px">
      <component :is="formComponent" :initial="editingItem" @submit="save" @cancel="dialogVisible = false" />
    </el-dialog>
  </div>
</template>
