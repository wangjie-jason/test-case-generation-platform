<script setup lang="ts">
import { UploadFilled, Loading, Close } from '@element-plus/icons-vue'
import type { KnowledgeBase } from '@/types/project'

interface TaskItem {
  taskId: string
  title: string
  status: 'running' | 'done' | 'error'
  genProgress: string
  cases: unknown[]
}

const props = defineProps<{
  parsedFilename: string
  isParsing: boolean
  isClarifying: boolean
  runningCount: number
  taskList: TaskItem[]
  activeTaskId: string | null
  kbs: KnowledgeBase[]
  /** PRD 上传的实际执行者。必须把 Promise 原样返回给 el-upload 的 http-request，
   *  否则 element-plus 不会调 onSuccess，文件条目会永远卡在「上传中」。 */
  parsePrd: (file: File) => Promise<void>
}>()

// 输入类字段一律 v-model 双向绑定，父组件直接把 store 的 ref 接上来
const inputMode = defineModel<'text' | 'file'>('inputMode', { required: true })
const requirementText = defineModel<string>('requirementText', { required: true })
const batchName = defineModel<string>('batchName', { required: true })
const selectedKbs = defineModel<string[]>('selectedKbs', { required: true })
const clarifiedText = defineModel<string>('clarifiedText', { required: true })

const emit = defineEmits<{
  (e: 'clarify'): void
  (e: 'generate'): void
  (e: 'viewTask', id: string): void
  (e: 'dismissTask', id: string): void
}>()

// el-upload 的 http-request：返回 Promise 才能让上传条目走到成功态
function onPrdUpload(options: { file: File }) { return props.parsePrd(options.file) }
</script>

<template>
  <el-card>
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span>需求输入</span>
        <el-radio-group v-model="inputMode" size="small">
          <el-radio-button value="text">粘贴文本</el-radio-button>
          <el-radio-button value="file">上传PRD</el-radio-button>
        </el-radio-group>
      </div>
    </template>
    <template v-if="inputMode === 'text'">
      <el-input v-model="requirementText" type="textarea" :rows="10" placeholder="粘贴需求描述或PRD内容..." />
    </template>
    <template v-else>
      <el-upload :auto-upload="true" :show-file-list="true" :http-request="onPrdUpload"
                 accept=".pdf,.docx,.md,.txt" :limit="1" drag>
        <el-icon><UploadFilled /></el-icon>
        <div>拖拽或点击上传 PRD</div>
      </el-upload>
      <div v-if="isParsing" style="text-align:center;padding:8px">解析中...</div>
      <el-input v-if="parsedFilename" v-model="requirementText" type="textarea" :rows="8" style="margin-top:8px" />
    </template>
    <div style="margin-top:12px">
      <div class="label">批次名称（用于区分不同需求）：</div>
      <el-input v-model="batchName" placeholder="如：xxx需求测试用例" maxlength="100" />
    </div>
    <div style="margin-top:12px">
      <div class="label">选择知识库（可多选，空=不限）：</div>
      <el-select v-model="selectedKbs" multiple placeholder="选择知识库" collapse-tags style="width:100%">
        <el-option v-for="k in kbs" :key="k.id" :label="k.name" :value="k.id" />
      </el-select>
    </div>
    <el-button :loading="isClarifying" @click="emit('clarify')" style="margin-top:12px;width:100%">
      {{ isClarifying ? '正在补全需求...' : '① 用知识库补全需求（可选）' }}
    </el-button>
    <div v-if="clarifiedText" class="clarify-box">
      <div class="clarify-hint">
        已根据知识库补全下方需求，可直接修改。生成时将<strong>以此为准</strong>（留空则用上方原始需求）。
      </div>
      <el-input v-model="clarifiedText" type="textarea" :autosize="{ minRows: 6, maxRows: 16 }"
                placeholder="补全后的结构化需求" />
      <el-button link type="info" size="small" @click="clarifiedText = ''">清除补全，改用原始需求</el-button>
    </div>

    <el-button type="primary" size="large" @click="emit('generate')" style="margin-top:12px;width:100%">
      {{ runningCount > 0 ? `② 生成测试用例（另起一个，当前 ${runningCount} 个进行中）` : (clarifiedText ? '② 按补全需求生成测试用例' : '生成测试用例') }}
    </el-button>

    <!-- 并行任务列表：可同时进行多个生成，点击查看各自进度/结果 -->
    <div v-if="taskList.length" class="task-list">
      <div class="task-list-title">生成任务（{{ taskList.length }}）</div>
      <div v-for="t in taskList" :key="t.taskId" class="task-item"
           :class="{ active: t.taskId === activeTaskId }"
           @click="emit('viewTask', t.taskId)">
        <el-icon v-if="t.status === 'running'" class="spin task-status"><Loading /></el-icon>
        <span v-else class="task-status" :class="t.status">{{ t.status === 'done' ? '✓' : '✕' }}</span>
        <span class="task-name">{{ t.title }}</span>
        <span class="task-meta">
          {{ t.status === 'running' ? (t.genProgress || '生成中') : (t.status === 'done' ? `${t.cases.length} 条` : '失败') }}
        </span>
        <el-icon v-if="t.status !== 'running'" class="task-close" @click.stop="emit('dismissTask', t.taskId)"><Close /></el-icon>
      </div>
    </div>
  </el-card>
</template>

<style scoped>
.label { font-size: 13px; color: #606266; margin-bottom: 4px; }
.clarify-box { margin-top: 10px; padding: 10px; border: 1px solid #d9ecff; border-radius: 8px; background: #f5faff; }
.clarify-hint { font-size: 12px; color: #606266; line-height: 1.5; margin-bottom: 8px; }
.task-list { margin-top: 14px; border-top: 1px solid #ebeef5; padding-top: 10px; }
.task-list-title { font-size: 12px; color: #909399; margin-bottom: 6px; }
.task-item { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.task-item:hover { background: #f5f7fa; }
.task-item.active { background: #ecf5ff; }
.task-status { flex-shrink: 0; width: 16px; text-align: center; }
.task-status.done { color: #67C23A; }
.task-status.error { color: #F56C6C; }
.task-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-meta { flex-shrink: 0; font-size: 12px; color: #909399; max-width: 40%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-close { flex-shrink: 0; color: #c0c4cc; }
.task-close:hover { color: #F56C6C; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
</style>
