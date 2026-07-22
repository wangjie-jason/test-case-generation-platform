<script setup lang="ts">
import { ref, computed } from 'vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import { ElMessage, ElMessageBox } from 'element-plus'
const props = defineProps<{ kbId: string }>()
const store = useKnowledgeStore()
const filters = computed(() => store.prdDocuments)

// ── 本地文件上传 ──
async function handleUpload(options: any) {
  try { await store.uploadPrd(props.kbId, options.file, (pct: number) => options.onProgress({ percent: pct })); ElMessage.success('上传成功') }
  catch (e: any) { ElMessage.error(e.message) }
}

// ── 从飞书导入 ──
const feishuDialogVisible = ref(false)
const feishuUrl = ref('')
const feishuLoading = ref(false)
async function submitFeishuImport() {
  const url = feishuUrl.value.trim()
  if (!url) { ElMessage.warning('请粘贴飞书文档链接'); return }
  feishuLoading.value = true
  try {
    await store.importPrdFromFeishu(props.kbId, url)
    ElMessage.success('从飞书导入成功')
    feishuDialogVisible.value = false
    feishuUrl.value = ''
  } catch (e: any) {
    // 后端把飞书错误信息塞在 response.data.detail 里
    const msg = e?.response?.data?.detail || e?.message || '导入失败'
    ElMessage.error(msg)
  } finally {
    feishuLoading.value = false
  }
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
    <div style="display:flex;gap:12px;align-items:center;margin-bottom:12px;flex-wrap:wrap">
      <el-upload :auto-upload="true" :show-file-list="false" :http-request="handleUpload" accept=".pdf,.docx,.md,.txt" :limit="1">
        <el-button type="primary">上传 PRD</el-button>
      </el-upload>
      <el-button type="success" plain @click="feishuDialogVisible = true">从飞书导入</el-button>
      <span style="color:#909399;font-size:12px">支持 PDF/Word/MD/TXT，或粘贴飞书 Wiki / 云文档链接</span>
    </div>

    <el-table :data="filters" border stripe>
      <el-table-column prop="filename" label="文件名" />
      <el-table-column label="来源" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.source_type === 'feishu'" type="success" size="small">飞书</el-tag>
          <el-tag v-else type="info" size="small">本地</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="file_format" label="格式" width="70" />
      <el-table-column label="预览" min-width="300">
        <template #default="{ row }"><div style="max-height:40px;overflow:hidden;font-size:12px;color:#606266">{{ row.raw_text.slice(0, 150) }}</div></template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{ row }"><el-button link type="primary" @click="preview(row)">查看</el-button><el-button link type="danger" @click="handleDelete(row.id)">删除</el-button></template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!filters.length" description="暂无PRD文档" />

    <!-- 飞书导入弹窗 -->
    <el-dialog v-model="feishuDialogVisible" title="从飞书导入 PRD" width="560px">
      <el-form label-position="top">
        <el-form-item label="飞书文档链接">
          <el-input
            v-model="feishuUrl"
            type="textarea"
            :rows="3"
            placeholder="粘贴飞书 Wiki 节点、云文档 (/docx/xxx) 或旧版文档 (/docs/xxx) 的完整 URL"
          />
        </el-form-item>
        <div style="color:#909399;font-size:12px;line-height:1.7">
          <div>• 支持的链接：<code>/wiki/xxx</code>、<code>/docx/xxx</code>、<code>/docs/xxx</code></div>
          <div>• 表格会转成 Markdown 表格，尽量保留结构；图片、电子表格等类型暂不支持</div>
          <div>• 同一份飞书文档重复导入会<b>覆盖</b>之前的内容并重建向量索引</div>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="feishuDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="feishuLoading" @click="submitFeishuImport">导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>
