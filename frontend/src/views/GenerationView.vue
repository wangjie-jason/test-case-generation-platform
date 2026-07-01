<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { storeToRefs } from 'pinia'
import { generationApi, type CaseRecord } from '@/api/generation'
import { ElMessage } from 'element-plus'
import { useGenerationStore } from '@/stores/generation'
import { UploadFilled, Loading, Close } from '@element-plus/icons-vue'

const store = useGenerationStore()
// 生成状态保存在 store 中，切换页面/tab 后回到本页仍保留实时进度与结果
const {
  kbs, selectedKbs, requirementText, batchName, inputMode, isParsing, parsedFilename,
  tabActive, isGenerating, cases, genProgress, streamText, knowledgeCounts,
  knowledgeMatches, history, taskList, activeTaskId, runningCount,
  clarifiedText, isClarifying,
} = storeToRefs(store)

onMounted(() => { store.fetchKbs(); store.fetchHistory() })

function handlePrdUpload(options: any) {
  return store.parsePrd(options.file)
}

function handleGenerate() {
  return store.generate()
}

function handleClarify() {
  return store.clarify()
}

async function downloadCases() {
  if (!cases.value.length) return
  try {
    const blob = await generationApi.exportCases(cases.value)
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    const name = batchName.value || new Date().toISOString().slice(0, 10)
    a.download = `${name}.xlsx`
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (e: any) { ElMessage.error(e.message) }
}

const kSummary = computed(() => {
  const p: string[] = []
  if (knowledgeCounts.value.field_dicts_count) p.push(`${knowledgeCounts.value.field_dicts_count} 字段`)
  if (knowledgeCounts.value.business_rules_count) p.push(`${knowledgeCounts.value.business_rules_count} 规则`)
  if (knowledgeCounts.value.state_machines_count) p.push(`${knowledgeCounts.value.state_machines_count} 状态`)
  if (knowledgeCounts.value.term_mappings_count) p.push(`${knowledgeCounts.value.term_mappings_count} 术语`)
  if (knowledgeCounts.value.prd_chunks_count) p.push(`${knowledgeCounts.value.prd_chunks_count} PRD`)
  if (knowledgeCounts.value.defect_chunks_count) p.push(`${knowledgeCounts.value.defect_chunks_count} 缺陷`)
  if (knowledgeCounts.value.historical_cases_count) p.push(`${knowledgeCounts.value.historical_cases_count} 历史用例`)
  return p.join(' / ') || '无'
})

interface MatchGroup {
  key: string
  title: string
  countKey: string
  items: Array<Record<string, unknown>>
}

const matchGroups = computed<MatchGroup[]>(() => [
  { key: 'field_dicts', title: '字段字典', countKey: 'field_dicts_count', items: knowledgeMatches.value.field_dicts || [] },
  { key: 'business_rules', title: '业务规则', countKey: 'business_rules_count', items: knowledgeMatches.value.business_rules || [] },
  { key: 'state_machines', title: '状态流转', countKey: 'state_machines_count', items: knowledgeMatches.value.state_machines || [] },
  { key: 'term_mappings', title: '术语映射', countKey: 'term_mappings_count', items: knowledgeMatches.value.term_mappings || [] },
  { key: 'prd_chunks', title: 'PRD片段', countKey: 'prd_chunks_count', items: knowledgeMatches.value.prd_chunks || [] },
  { key: 'defect_chunks', title: '缺陷记录', countKey: 'defect_chunks_count', items: knowledgeMatches.value.defect_chunks || [] },
  { key: 'historical_cases', title: '历史用例', countKey: 'historical_cases_count', items: knowledgeMatches.value.historical_cases || [] },
].filter(g => g.items.length || knowledgeCounts.value[g.countKey]))

const hasKnowledgeMatches = computed(() => matchGroups.value.some(g => g.items.length))

function matchTitle(groupKey: string, item: Record<string, unknown>) {
  if (groupKey === 'field_dicts') return `${item.display_name || ''}${item.field_name ? `（${item.field_name}）` : ''}` || '字段'
  if (groupKey === 'business_rules') return String(item.rule_name || '业务规则')
  if (groupKey === 'state_machines') return `${item.entity || '对象'}：${item.from_state || '-'} → ${item.to_state || '-'}`
  if (groupKey === 'term_mappings') return `${item.ui_term || '术语'} → ${item.tech_field || '-'}`
  if (groupKey === 'defect_chunks') return String(item.title || '缺陷片段')
  if (groupKey === 'historical_cases') return '相似历史用例'
  return String(item.filename || item.id || '知识片段')
}

function matchDescription(groupKey: string, item: Record<string, unknown>) {
  const value = item.description || item.expression || item.condition || item.mapping_desc || item.text || ''
  const text = String(value || '')
  if (!text) return groupKey === 'field_dicts' && item.data_type ? `类型：${item.data_type}` : ''
  return text.length > 160 ? `${text.slice(0, 160)}...` : text
}

const batchGroups = computed(() => {
  const map: Record<string, any[]> = {}
  for (const c of history.value) { const bid = c.batch_id || 'unknown'; if (!map[bid]) map[bid] = []; map[bid].push(c) }
  return Object.entries(map).map(([bid, items]) => ({ batch_id: bid, req_text: items[0]?.req_text || '', created_at: items[0]?.created_at || '', total: items.length, items })).sort((a: any, b: any) => b.created_at.localeCompare(a.created_at))
})

async function downloadBatch(batch: { req_text?: string | null; created_at?: string; items: CaseRecord[] }) {
  try {
    const blob = await generationApi.exportCases(batch.items)
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    const name = batch.req_text || batch.created_at?.slice(0, 10) || 'test_cases'
    a.download = `${name}.xlsx`
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (e: any) { ElMessage.error(e.message) }
}
</script>

<template>
  <div class="gen-view">
    <h2 style="margin-bottom:16px">用例生成</h2>
    <el-tabs v-model="tabActive">
      <el-tab-pane label="生成用例" name="generate" />
      <el-tab-pane label="历史记录" name="history" />
    </el-tabs>

    <div v-if="tabActive === 'generate'" class="gen-container">
      <div class="top-panels">
        <div class="input-panel">
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
              <el-upload :auto-upload="true" :show-file-list="true" :http-request="handlePrdUpload" accept=".pdf,.docx,.md,.txt" :limit="1" drag>
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
            <el-button
              :loading="isClarifying"
              @click="handleClarify"
              style="margin-top:12px;width:100%"
            >
              {{ isClarifying ? '正在补全需求...' : '① 用知识库补全需求（可选）' }}
            </el-button>
            <div v-if="clarifiedText" class="clarify-box">
              <div class="clarify-hint">
                已根据知识库补全下方需求，可直接修改。生成时将<strong>以此为准</strong>（留空则用上方原始需求）。
              </div>
              <el-input
                v-model="clarifiedText"
                type="textarea"
                :autosize="{ minRows: 6, maxRows: 16 }"
                placeholder="补全后的结构化需求"
              />
              <el-button link type="info" size="small" @click="clarifiedText = ''">清除补全，改用原始需求</el-button>
            </div>

            <el-button type="primary" size="large" @click="handleGenerate" style="margin-top:12px;width:100%">
              {{ runningCount > 0 ? `② 生成测试用例（另起一个，当前 ${runningCount} 个进行中）` : (clarifiedText ? '② 按补全需求生成测试用例' : '生成测试用例') }}
            </el-button>

            <!-- 并行任务列表：可同时进行多个生成，点击查看各自进度/结果 -->
            <div v-if="taskList.length" class="task-list">
              <div class="task-list-title">生成任务（{{ taskList.length }}）</div>
              <div
                v-for="t in taskList"
                :key="t.taskId"
                class="task-item"
                :class="{ active: t.taskId === activeTaskId }"
                @click="store.viewTask(t.taskId)"
              >
                <el-icon v-if="t.status === 'running'" class="spin task-status"><Loading /></el-icon>
                <span v-else class="task-status" :class="t.status">{{ t.status === 'done' ? '✓' : '✕' }}</span>
                <span class="task-name">{{ t.title }}</span>
                <span class="task-meta">
                  {{ t.status === 'running' ? (t.genProgress || '生成中') : (t.status === 'done' ? `${t.cases.length} 条` : '失败') }}
                </span>
                <el-icon v-if="t.status !== 'running'" class="task-close" @click.stop="store.dismissTask(t.taskId)"><Close /></el-icon>
              </div>
            </div>
          </el-card>
        </div>

        <div class="knowledge-panel">
          <el-card>
            <template #header>
              <div class="results-toolbar">
                <span>检索预警命中知识</span>
                <el-tag v-if="kSummary !== '无'" size="small" type="warning">{{ kSummary }}</el-tag>
              </div>
            </template>
            <el-alert v-if="isGenerating" :title="genProgress || '正在检索知识库并生成用例...'" type="info" :closable="false" />
            <template v-else-if="hasKnowledgeMatches">
              <div v-for="group in matchGroups" :key="group.key" class="match-group">
                <div class="match-group-title">
                  <span>{{ group.title }}</span>
                  <el-tag size="small" effect="plain">{{ group.items.length || knowledgeCounts[group.countKey] || 0 }}</el-tag>
                </div>
                <div v-for="(item, idx) in group.items" :key="`${group.key}-${idx}`" class="match-item">
                  <div class="match-title">{{ matchTitle(group.key, item) }}</div>
                  <div v-if="matchDescription(group.key, item)" class="match-desc">{{ matchDescription(group.key, item) }}</div>
                </div>
              </div>
            </template>
            <el-empty v-else :description="cases.length ? '未命中知识库内容' : '生成后显示命中的字段、规则、缺陷等知识'" />
          </el-card>
        </div>
      </div>

      <div class="output-panel">
        <el-card>
          <template #header>
            <div class="results-toolbar"><span>生成结果</span><el-button v-if="cases.length" size="small" type="success" @click="downloadCases">下载 Excel</el-button></div>
          </template>
          <el-alert v-if="isGenerating" :title="genProgress || '生成中...'" type="info" :closable="false" />
          <div v-if="isGenerating && streamText" class="stream-output">{{ streamText }}</div>
          <el-tag v-if="!isGenerating && cases.length" size="small" type="info" style="margin-bottom:8px">引用知识：{{ kSummary }}</el-tag>
          <div v-for="(c, idx) in cases" :key="idx" style="margin-bottom:8px">
            <el-collapse>
              <el-collapse-item>
                <template #title>
                  <span style="font-weight:bold;color:#409EFF">#{{ idx + 1 }}</span>
                  <el-tag v-if="c.priority" size="small" :type="c.priority === 'P0' ? 'danger' : c.priority === 'P1' ? 'warning' : 'info'" style="margin:0 8px">{{ c.priority }}</el-tag>
                  <span>{{ c.title }}</span>
                </template>
                <div v-if="c.precondition" style="margin-bottom:6px;font-size:13px">前置：{{ c.precondition }}</div>
                <div v-if="c.steps" style="margin-bottom:6px;font-size:13px;white-space:pre-wrap">步骤：{{ typeof c.steps === 'string' ? c.steps : JSON.stringify(c.steps) }}</div>
                <div v-if="c.expected_result" style="font-size:13px;color:#67C23A">预期：{{ c.expected_result }}</div>
              </el-collapse-item>
            </el-collapse>
          </div>
          <el-empty v-if="!isGenerating && !cases.length" description="输入需求后点击生成" />
        </el-card>
      </div>
    </div>

    <div v-if="tabActive === 'history'" class="history-tab">
      <el-card>
        <template #header><span>生成历史（{{ batchGroups.length }} 批次）</span></template>
        <div v-for="b in batchGroups" :key="b.batch_id" class="batch-card">
          <div class="batch-header">
            <div><strong class="batch-name">{{ b.req_text?.slice(0, 60) || '未命名需求' }}</strong><span class="batch-meta-info">{{ b.total }} 条 · {{ b.created_at?.slice(0, 16) }}</span></div>
            <el-button size="small" type="success" @click="downloadBatch(b)">下载 Excel</el-button>
          </div>
          <el-collapse>
            <el-collapse-item :title="`展开 ${b.total} 条用例`">
              <div v-for="c in b.items" :key="c.id" style="padding:6px;border-bottom:1px solid #f0f0f0;font-size:13px">
                <strong>{{ c.title }}</strong>
                <div v-if="c.expected_result" style="color:#909399">预期：{{ c.expected_result }}</div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
        <el-empty v-if="!batchGroups.length" description="暂无历史" />
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.gen-view { max-width: 1200px; margin: 0 auto; }
.gen-container { display: flex; flex-direction: column; gap: 24px; }
.top-panels { display: flex; gap: 24px; align-items: stretch; }
.input-panel { flex: 0 0 420px; }
.input-panel > :deep(.el-card), .knowledge-panel > :deep(.el-card) { height: 100%; }
.knowledge-panel { flex: 1; min-width: 0; }
.output-panel { width: 100%; }
.label { font-size: 13px; color: #606266; margin-bottom: 4px; }
.results-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.stream-output { margin-top: 10px; padding: 10px 12px; background: #1e1e1e; color: #d4d4d4; border-radius: 6px; font-family: 'SFMono-Regular', Menlo, Consolas, monospace; font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; max-height: 360px; overflow-y: auto; }
.match-group { margin-bottom: 14px; }
.match-group-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 13px; font-weight: 600; color: #303133; }
.match-item { padding: 8px 10px; margin-bottom: 8px; border: 1px solid #ebeef5; border-radius: 8px; background: #fafafa; }
.match-title { font-size: 13px; font-weight: 600; color: #409EFF; }
.match-desc { margin-top: 4px; font-size: 12px; line-height: 1.5; color: #606266; white-space: pre-wrap; word-break: break-word; }
.batch-card { border: 1px solid #e4e7ed; border-radius: 8px; padding: 14px; margin-bottom: 12px; }
.batch-header { display: flex; justify-content: space-between; align-items: center; }
.batch-name { font-size: 14px; display: block; }
.batch-meta-info { display: block; font-size: 12px; color: #909399; margin-top: 2px; }
.batch-req { display: block; font-size: 12px; color: #909399; }
.batch-time { display: block; font-size: 11px; color: #c0c4cc; }
.history-tab { max-width: 960px; margin: 0 auto; }
.task-list { margin-top: 14px; border-top: 1px solid #ebeef5; padding-top: 10px; }
.task-list-title { font-size: 12px; color: #909399; margin-bottom: 6px; }
.clarify-box { margin-top: 10px; padding: 10px; border: 1px solid #d9ecff; border-radius: 8px; background: #f5faff; }
.clarify-hint { font-size: 12px; color: #606266; line-height: 1.5; margin-bottom: 8px; }
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
@media (max-width: 900px) {
  .top-panels { flex-direction: column; }
  .input-panel { flex: none; }
}
</style>
