<script setup lang="ts">
import { onMounted, onUnmounted, computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { generationApi, type CaseRecord, type BatchSummary } from '@/api/generation'
import { ElMessage } from 'element-plus'
import { useGenerationStore } from '@/stores/generation'
import { UploadFilled, Loading, Close } from '@element-plus/icons-vue'

const store = useGenerationStore()
// 生成状态保存在 store 中，切换页面/tab 后回到本页仍保留实时进度与结果
const {
  kbs, selectedKbs, requirementText, batchName, inputMode, isParsing, parsedFilename,
  tabActive, isGenerating, cases, genProgress, streamText, knowledgeCounts,
  knowledgeMatches, taskList, activeTaskId, runningCount, modules, agents,
  reviewAgents, supplementAgents,
  clarifiedText, isClarifying, historyDirty, elapsed, taskStartedAt,
} = storeToRefs(store)

// 全局秒表：每 200ms 自增一次，作为「实时耗时」计算的时间基准。
// 运行中的 agent / 总耗时都以 now - startedAt 现算，now 一变视图就重算，实现秒表效果。
// 只在有任务运行时才开表，避免空转。
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | null = null
watch(runningCount, (n) => {
  if (n > 0 && timer == null) {
    timer = setInterval(() => { now.value = Date.now() }, 200)
  } else if (n === 0 && timer != null) {
    now.value = Date.now()  // 收表前再刷一次，让停下的瞬间数值贴近真实
    clearInterval(timer); timer = null
  }
}, { immediate: true })
onUnmounted(() => { if (timer != null) { clearInterval(timer); timer = null } })

// 把秒数格式化为可读耗时：<60s 显示「12.3s」，≥60s 显示「1分23秒」。
function formatDuration(sec: number | null | undefined): string {
  if (sec == null) return ''
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}分${s}秒`
}

// 单个 agent 的显示耗时：运行中用秒表现算（保留 1 位小数），完成/失败后用后端权威值。
function agentSeconds(a: { status: string; startedAt: number | null; elapsed: number | null }): number | null {
  if (a.status === 'running' && a.startedAt != null) {
    return Math.round((now.value - a.startedAt) / 100) / 10
  }
  return a.elapsed
}

// 当前查看任务的总耗时：完成后用后端权威值，运行中用秒表从 startedAt 现算。
const totalSeconds = computed<number | null>(() => {
  if (elapsed.value != null) return elapsed.value
  if (isGenerating.value && taskStartedAt.value != null) {
    return Math.round((now.value - taskStartedAt.value) / 100) / 10
  }
  return null
})

// 展开的 agent 卡片（可多开）。默认全部收起，只有用户手动点开才展开——不做任何自动展开。
const openAgents = ref<number[]>([])
// 评审 / 补充阶段的卡片各自独立的展开态（它们的 index 各自从 0 起，不能共用 openAgents）。
const openReviewAgents = ref<number[]>([])
const openSupplementAgents = ref<number[]>([])

// 历史记录：先拉批次汇总渲染折叠卡片，点开某批时再懒加载该批全量用例。
// 老实现是一次拉 /cases（写死 200 上限），大批次会被截断——现在按 batch_id 精确拉。
const batches = ref<BatchSummary[]>([])
const batchItems = ref<Record<string, CaseRecord[]>>({})
const loadingBatch = ref<Record<string, boolean>>({})

async function fetchBatches() {
  try {
    batches.value = await generationApi.listBatches()
  } catch { ElMessage.error('加载生成历史失败') }
}

async function loadBatchItems(bid: string) {
  if (batchItems.value[bid] || loadingBatch.value[bid]) return
  loadingBatch.value[bid] = true
  try {
    batchItems.value[bid] = await generationApi.listCases(bid)
  } catch (e: any) {
    ElMessage.error(e?.message || '加载批次失败')
  } finally {
    loadingBatch.value[bid] = false
  }
}

onMounted(() => { store.fetchKbs(); fetchBatches() })

// 生成结束时 store 会把 historyDirty +1，触发这里重拉批次汇总 + 清空 items 缓存，
// 避免旧的懒加载数据里少了刚生成的一批。
watch(historyDirty, () => {
  batchItems.value = {}
  fetchBatches()
})

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

const batchGroups = computed(() => batches.value.map(b => ({
  ...b,
  items: batchItems.value[b.batch_id] || [],
  loading: !!loadingBatch.value[b.batch_id],
})))

async function downloadBatch(batch: BatchSummary) {
  try {
    // 保证下载到的是全量：即使用户没展开也现拉一次。
    const items = batchItems.value[batch.batch_id] || await generationApi.listCases(batch.batch_id)
    batchItems.value[batch.batch_id] = items
    const blob = await generationApi.exportCases(items)
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
            <!-- 命中知识内容区：设最大高度，命中过多时栏内滚动，避免撑长整个页面 -->
            <div class="knowledge-body">
              <el-alert v-if="isGenerating && !hasKnowledgeMatches" :title="genProgress || '正在检索知识库并生成用例...'" type="info" :closable="false" />
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
            </div>
          </el-card>
        </div>
      </div>

      <div class="output-panel">
        <el-card>
          <template #header>
            <div class="results-toolbar">
              <span>生成结果
                <span v-if="totalSeconds != null" class="total-time">· 总耗时 ⏱ {{ formatDuration(totalSeconds) }}</span>
              </span>
              <el-button v-if="cases.length" size="small" type="success" @click="downloadCases">下载 Excel</el-button>
            </div>
          </template>
          <el-alert v-if="isGenerating" :title="genProgress || '生成中...'" type="info" :closable="false" />
          <div v-if="modules.length" class="module-list">
            <span class="module-list-label">拆分模块（{{ modules.length }}）：</span>
            <el-tag v-for="(m, i) in modules" :key="i" size="small" effect="plain" class="module-tag">{{ m }}</el-tag>
          </div>

          <!-- Agent 卡片区：每个模块一张卡，可同时展开多张各看各的流。
               生成中展示该 agent 的实时原始流；完成后替换为解析好的用例列表。 -->
          <div v-if="agents.length" class="agent-area">
            <el-collapse v-model="openAgents">
              <el-collapse-item v-for="a in agents" :key="a.index" :name="a.index">
                <template #title>
                  <el-icon v-if="a.status === 'running'" class="spin agent-ico"><Loading /></el-icon>
                  <span v-else-if="a.status === 'done'" class="agent-ico done">✓</span>
                  <span v-else class="agent-ico failed">✕</span>
                  <span class="agent-name">{{ a.module }}</span>
                  <span class="agent-meta">
                    {{ a.status === 'running' ? '生成中…' : a.status === 'failed' ? '失败' : `${a.cases.length} 条` }}
                    <span v-if="agentSeconds(a) != null" class="agent-time">· ⏱ {{ formatDuration(agentSeconds(a)) }}</span>
                  </span>
                </template>
                <!-- 完成：展示解析好的用例列表 -->
                <template v-if="a.status === 'done'">
                  <div v-if="!a.cases.length" class="agent-empty">该模块未产出用例</div>
                  <div v-for="(c, ci) in a.cases" :key="ci" class="agent-case">
                    <el-tag v-if="c.priority" size="small" :type="c.priority === 'P0' ? 'danger' : c.priority === 'P1' ? 'warning' : 'info'" effect="plain" style="margin-right:6px">{{ c.priority }}</el-tag>
                    <strong>{{ c.title }}</strong>
                    <div v-if="c.precondition" class="agent-case-line">前置：{{ c.precondition }}</div>
                    <div v-if="c.steps" class="agent-case-line" style="white-space:pre-wrap">步骤：{{ typeof c.steps === 'string' ? c.steps : JSON.stringify(c.steps) }}</div>
                    <div v-if="c.expected_result" class="agent-case-line" style="color:#67C23A">预期：{{ c.expected_result }}</div>
                  </div>
                </template>
                <!-- 失败 -->
                <div v-else-if="a.status === 'failed'" class="agent-empty">该模块生成失败，已跳过（其余模块不受影响）</div>
                <!-- 生成中：优先展示正文实时流；正文未开始时展示思考流（🤔 深度思考中） -->
                <template v-else>
                  <div v-if="a.streamText" class="stream-output">{{ a.streamText }}</div>
                  <div v-else-if="a.thinkText" class="stream-output thinking">
                    <div class="thinking-badge">🤔 深度思考中…</div>{{ a.thinkText }}
                  </div>
                  <div v-else class="stream-output thinking">🤔 深度思考中…</div>
                </template>
              </el-collapse-item>
            </el-collapse>
          </div>

          <!-- 单批（无模块拆分）时的全局流式兜底 -->
          <div v-if="isGenerating && streamText && !agents.length" class="stream-output">{{ streamText }}</div>

          <!-- 评审 agent 卡片区：每个模块分组一张卡，实时流式展示评审过程（保留/删除判断）。 -->
          <div v-if="reviewAgents.length" class="agent-area">
            <div class="phase-label">🔍 测试专家分模块并行评审</div>
            <el-collapse v-model="openReviewAgents">
              <el-collapse-item v-for="a in reviewAgents" :key="a.index" :name="a.index">
                <template #title>
                  <el-icon v-if="a.status === 'running'" class="spin agent-ico"><Loading /></el-icon>
                  <span v-else-if="a.status === 'done'" class="agent-ico done">✓</span>
                  <span v-else class="agent-ico failed">✕</span>
                  <span class="agent-name">{{ a.module }}</span>
                  <span class="agent-meta">
                    {{ a.status === 'running' ? '评审中…' : a.status === 'failed' ? '失败' : a.summary }}
                    <span v-if="agentSeconds(a) != null" class="agent-time">· ⏱ {{ formatDuration(agentSeconds(a)) }}</span>
                  </span>
                </template>
                <div v-if="a.status === 'failed'" class="agent-empty">该模块评审失败，已跳过（默认全部保留）</div>
                <template v-else>
                  <div v-if="a.streamText" class="stream-output">{{ a.streamText }}</div>
                  <div v-else-if="a.thinkText" class="stream-output thinking">
                    <div class="thinking-badge">🤔 深度思考中…</div>{{ a.thinkText }}
                  </div>
                  <div v-else class="stream-output thinking">🤔 深度思考中…</div>
                </template>
              </el-collapse-item>
            </el-collapse>
          </div>

          <!-- 补充 agent 卡片区：被删场景/遗漏场景各一张卡，实时流式展示补充用例的生成。 -->
          <div v-if="supplementAgents.length" class="agent-area">
            <div class="phase-label">➕ 分模块并行补充遗漏场景</div>
            <el-collapse v-model="openSupplementAgents">
              <el-collapse-item v-for="a in supplementAgents" :key="a.index" :name="a.index">
                <template #title>
                  <el-icon v-if="a.status === 'running'" class="spin agent-ico"><Loading /></el-icon>
                  <span v-else-if="a.status === 'done'" class="agent-ico done">✓</span>
                  <span v-else class="agent-ico failed">✕</span>
                  <span class="agent-name">{{ a.module }}</span>
                  <span class="agent-meta">
                    {{ a.status === 'running' ? '补充中…' : a.status === 'failed' ? '失败' : a.summary }}
                    <span v-if="agentSeconds(a) != null" class="agent-time">· ⏱ {{ formatDuration(agentSeconds(a)) }}</span>
                  </span>
                </template>
                <div v-if="a.status === 'failed'" class="agent-empty">该组补充失败，已跳过</div>
                <template v-else>
                  <div v-if="a.streamText" class="stream-output">{{ a.streamText }}</div>
                  <div v-else-if="a.thinkText" class="stream-output thinking">
                    <div class="thinking-badge">🤔 深度思考中…</div>{{ a.thinkText }}
                  </div>
                  <div v-else class="stream-output thinking">🤔 深度思考中…</div>
                </template>
              </el-collapse-item>
            </el-collapse>
          </div>

          <el-tag v-if="kSummary !== '无'" size="small" type="info" style="margin:8px 0">引用知识：{{ kSummary }}</el-tag>
          <div v-if="cases.length" class="final-cases-title">最终用例（评审+补充后，共 {{ cases.length }} 条）</div>
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
        <template #header>
          <div class="results-toolbar">
            <span>生成历史（{{ batchGroups.length }} 批次）</span>
            <el-button size="small" @click="fetchBatches">刷新</el-button>
          </div>
        </template>
        <div v-for="b in batchGroups" :key="b.batch_id" class="batch-card">
          <div class="batch-header">
            <div><strong class="batch-name">{{ b.req_text?.slice(0, 60) || '未命名需求' }}</strong><span class="batch-meta-info">{{ b.total }} 条 · {{ b.created_at?.slice(0, 16) }}</span></div>
            <el-button size="small" type="success" @click="downloadBatch(b)">下载 Excel</el-button>
          </div>
          <el-collapse @change="(val: string | string[]) => (Array.isArray(val) ? val : [val]).includes(b.batch_id) && loadBatchItems(b.batch_id)">
            <el-collapse-item :title="`展开 ${b.total} 条用例`" :name="b.batch_id">
              <div v-if="b.loading" style="text-align:center;color:#909399;padding:10px">加载中...</div>
              <div v-else-if="!b.items.length" style="text-align:center;color:#909399;padding:10px">暂无数据</div>
              <div v-else v-for="c in b.items" :key="c.id" style="padding:6px;border-bottom:1px solid #f0f0f0;font-size:13px">
                <el-tag v-if="c.priority" size="small" :type="c.priority === 'P0' ? 'danger' : c.priority === 'P1' ? 'warning' : 'info'" effect="plain" style="margin-right:6px">{{ c.priority }}</el-tag>
                <strong>{{ c.title }}</strong>
                <div v-if="c.precondition" style="color:#909399">前置：{{ c.precondition }}</div>
                <div v-if="c.steps" style="color:#909399;white-space:pre-wrap">步骤：{{ typeof c.steps === 'string' ? c.steps : JSON.stringify(c.steps) }}</div>
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
/* 用 grid 固定两栏：左栏 420px，右栏 minmax(320px,1fr) 保证下限，任何生成阶段都不会被挤成 0
   宽而消失（flex 布局下 input-panel 不能收缩、knowledge-panel min-width:0 会被压没的根因）。 */
.top-panels { display: grid; grid-template-columns: 420px minmax(320px, 1fr); gap: 24px; align-items: stretch; }
.input-panel { min-width: 0; }
/* 撑满宽度的相邻按钮之间，去掉 Element Plus 默认的 margin-left，避免整行按钮被右推、看起来不居中 */
.input-panel :deep(.el-button + .el-button) { margin-left: 0; }
.input-panel > :deep(.el-card), .knowledge-panel > :deep(.el-card) { height: 100%; }
.knowledge-panel { min-width: 0; }
/* 命中知识过多时栏内滚动，不撑长整个页面 */
.knowledge-body { max-height: 60vh; overflow-y: auto; padding-right: 4px; }
.output-panel { width: 100%; }
.label { font-size: 13px; color: #606266; margin-bottom: 4px; }
.results-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.stream-output { margin-top: 10px; padding: 10px 12px; background: #1e1e1e; color: #d4d4d4; border-radius: 6px; font-family: 'SFMono-Regular', Menlo, Consolas, monospace; font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; max-height: 360px; overflow-y: auto; }
.stream-output.thinking { background: #2a2a2a; color: #9aa0a6; font-style: italic; }
.thinking-badge { font-style: normal; color: #c8a95a; margin-bottom: 6px; font-weight: 600; }
.module-list { margin: 8px 0; display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.module-list-label { font-size: 13px; color: #606266; font-weight: 600; }
.module-tag { margin: 0; }
.agent-area { margin: 10px 0; }
.phase-label { font-size: 13px; font-weight: 600; color: #606266; margin: 6px 0; }
.agent-ico { flex-shrink: 0; width: 18px; text-align: center; margin-right: 6px; }
.agent-ico.done { color: #67C23A; font-weight: bold; }
.agent-ico.failed { color: #F56C6C; font-weight: bold; }
.agent-name { font-weight: 600; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-meta { flex-shrink: 0; font-size: 12px; color: #909399; margin-left: 8px; }
.agent-time { color: #409EFF; }
.agent-empty { font-size: 13px; color: #909399; padding: 6px 0; }
.agent-case { padding: 6px 0; border-bottom: 1px solid #f0f0f0; font-size: 13px; }
.agent-case-line { color: #606266; margin-top: 2px; }
.final-cases-title { font-size: 14px; font-weight: 600; color: #303133; margin: 12px 0 8px; }
.total-time { font-weight: 400; font-size: 13px; color: #409EFF; }
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
  /* 窄屏改为单列纵向堆叠，两栏各占满整行 */
  .top-panels { grid-template-columns: 1fr; }
}
</style>
