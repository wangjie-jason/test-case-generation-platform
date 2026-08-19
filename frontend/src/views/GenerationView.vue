<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { useGenerationStore } from '@/stores/generation'
import { generationApi, type CaseRecord } from '@/api/generation'
import { saveBlob } from '@/utils/saveBlob'
import { useBatchList } from '@/composables/useBatchList'
import { useKnowledgeMatches } from '@/composables/useKnowledgeMatches'
import RequirementInputCard from '@/components/generation/RequirementInputCard.vue'
import KnowledgeMatchPanel from '@/components/generation/KnowledgeMatchPanel.vue'
import GenerationOutputCard from '@/components/generation/GenerationOutputCard.vue'
import GenerationHistoryTab from '@/components/generation/GenerationHistoryTab.vue'

const store = useGenerationStore()
// 生成状态保存在 store 中，切换页面/tab 后回到本页仍保留实时进度与结果
const {
  kbs, selectedKbs, requirementText, batchName, inputMode, isParsing, parsedFilename,
  tabActive, isGenerating, cases, genProgress, streamText, knowledgeCounts,
  knowledgeMatches, taskList, activeTaskId, runningCount, modules, agents,
  reviewAgents, supplementAgents,
  clarifiedText, isClarifying, historyDirty, elapsed, taskStartedAt,
} = storeToRefs(store)

// 历史记录：先拉批次汇总渲染折叠卡片，点开某批时再懒加载该批全量用例。
const {
  batches, batchItems, loadingBatch, expandedBatch,
  fetchBatches, toggleBatch, resetCache,
} = useBatchList('加载生成历史失败')

// 「刷新」按钮：连 items 缓存与展开态一起重置，否则已展开的批次仍显示旧的懒加载结果
function refreshHistory() {
  resetCache()
  fetchBatches()
}

// 历史页下载时若批次没展开过，会现拉一次全量；把结果回写缓存，之后展开不再请求。
function cacheBatchItems(batchId: string, items: CaseRecord[]) {
  batchItems.value[batchId] = items
}

onMounted(() => { store.fetchKbs(); fetchBatches() })

// 生成结束时 store 会把 historyDirty +1，触发这里重拉批次汇总 + 清空 items 缓存，
// 避免旧的懒加载数据里少了刚生成的一批。
watch(historyDirty, () => {
  batchItems.value = {}
  // 展开态一并收起：items 缓存清了，还留着展开的批次会显示"暂无数据"而不重新拉
  expandedBatch.value = {}
  fetchBatches()
})

function handlePrdUpload(file: File) { return store.parsePrd(file) }
function handleGenerate() { return store.generate() }
function handleClarify() { return store.clarify() }

async function downloadCases() {
  if (!cases.value.length) return
  try {
    const blob = await generationApi.exportCases(cases.value)
    const name = batchName.value || new Date().toISOString().slice(0, 10)
    saveBlob(blob, `${name}.xlsx`)
  } catch (e: any) { ElMessage.error(e.message) }
}

// 命中知识的条数摘要：与右侧命中面板同一份实现，避免两处各写一遍
const { summary: knowledgeSummary } = useKnowledgeMatches(knowledgeCounts, knowledgeMatches)
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
          <RequirementInputCard
            v-model:input-mode="inputMode"
            v-model:requirement-text="requirementText"
            v-model:batch-name="batchName"
            v-model:selected-kbs="selectedKbs"
            v-model:clarified-text="clarifiedText"
            :parsed-filename="parsedFilename"
            :is-parsing="isParsing"
            :is-clarifying="isClarifying"
            :running-count="runningCount"
            :task-list="taskList"
            :active-task-id="activeTaskId"
            :kbs="kbs"
            :parse-prd="handlePrdUpload"
            @clarify="handleClarify"
            @generate="handleGenerate"
            @viewTask="store.viewTask"
            @dismissTask="store.dismissTask"
          />
        </div>
        <div class="knowledge-panel">
          <KnowledgeMatchPanel
            :is-generating="isGenerating"
            :gen-progress="genProgress"
            :has-cases="cases.length > 0"
            :knowledge-counts="knowledgeCounts"
            :knowledge-matches="knowledgeMatches"
          />
        </div>
      </div>

      <div class="output-panel">
        <GenerationOutputCard
          :is-generating="isGenerating"
          :gen-progress="genProgress"
          :modules="modules"
          :agents="agents"
          :review-agents="reviewAgents"
          :supplement-agents="supplementAgents"
          :stream-text="streamText"
          :cases="cases"
          :knowledge-summary="knowledgeSummary"
          :running-count="runningCount"
          :task-started-at="taskStartedAt"
          :elapsed="elapsed"
          @download="downloadCases"
        />
      </div>
    </div>

    <div v-if="tabActive === 'history'">
      <GenerationHistoryTab
        :batches="batches"
        :batch-items="batchItems"
        :loading-batch="loadingBatch"
        :expanded-batch="expandedBatch"
        @refresh="refreshHistory"
        @toggle="toggleBatch"
        @cached="cacheBatchItems"
      />
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
.output-panel { width: 100%; }
@media (max-width: 900px) {
  /* 窄屏改为单列纵向堆叠，两栏各占满整行 */
  .top-panels { grid-template-columns: 1fr; }
}
</style>
