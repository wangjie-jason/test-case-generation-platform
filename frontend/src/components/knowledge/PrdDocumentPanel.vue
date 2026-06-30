<script setup lang="ts">
import { ref, computed } from 'vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import { ElMessage, ElMessageBox } from 'element-plus'
const props = defineProps<{ kbId: string }>()
const store = useKnowledgeStore()
const filters = computed(() => store.prdDocuments)
async function handleUpload(options: any) {
  try { await store.uploadPrd(props.kbId, options.file, (pct: number) => options.onProgress({ percent: pct })); ElMessage.success('上传成功') }
  catch (e: any) { ElMessage.error(e.message) }
}
async function handleDelete(id: string) {
  try { await ElMessageBox.confirm('确定删除？', '提示', { type: 'warning' }); await store.deletePrd(props.kbId, id); ElMessage.success('删除成功') }
  catch {}
}
function preview(item: any) {
  const w = window.open('', '_blank', 'width=800,height=600')
  if (!w) return
  const pre = w.document.createElement('pre')
  pre.style.cssText = 'white-space:pre-wrap;padding:16px;font-family:monospace'
  pre.textContent = item.raw_text || ''
  w.document.body.appendChild(pre)
}
</script>
<template>
  <div>
    <el-upload :auto-upload="true" :show-file-list="true" :http-request="handleUpload" accept=".pdf,.docx,.md,.txt" :limit="1" style="margin-bottom:12px">
      <el-button type="primary">上传 PRD</el-button>
      <template #tip><span style="margin-left:8px;color:#909399;font-size:12px">PDF/Word/MD/TXT</span></template>
    </el-upload>
    <el-table :data="filters" border stripe>
      <el-table-column prop="filename" label="文件名" />
      <el-table-column prop="file_format" label="格式" width="70" />
      <el-table-column label="预览" min-width="300">
        <template #default="{ row }"><div style="max-height:40px;overflow:hidden;font-size:12px;color:#606266">{{ row.raw_text.slice(0, 150) }}</div></template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{ row }"><el-button link type="primary" @click="preview(row)">查看</el-button><el-button link type="danger" @click="handleDelete(row.id)">删除</el-button></template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!filters.length" description="暂无PRD文档" />
  </div>
</template>
