<script setup lang="ts">
import { ref } from 'vue'
import AgentStreamCard from './AgentStreamCard.vue'
import { priorityTagType } from '@/utils/priority'

defineProps<{
  isGenerating: boolean
  genProgress: string
  modules: string[]
  agents: any[]   // AgentState from store; 形态与 AgentStreamCard 一致，故意不重复声明
  reviewAgents: any[]
  supplementAgents: any[]
  streamText: string
  cases: any[]     // GeneratedTestCase[] with optional origin
  totalSeconds: number | null
  hasCases: boolean
  knowledgeSummary: string
  formatDuration: (sec: number | null | undefined) => string
  agentSeconds: (a: any) => number | null
  downloadCases: () => void
}>()

// 三个阶段的 agent 卡片各自独立展开态（它们的 index 各自从 0 起，不能共用）。
const openAgents = ref<number[]>([])
const openReviewAgents = ref<number[]>([])
const openSupplementAgents = ref<number[]>([])
</script>

<template>
  <el-card>
    <template #header>
      <div class="results-toolbar">
        <span>生成结果
          <span v-if="totalSeconds != null" class="total-time">· 总耗时 ⏱ {{ formatDuration(totalSeconds) }}</span>
        </span>
        <el-button v-if="hasCases" size="small" type="success" @click="downloadCases">下载 Excel</el-button>
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
        <AgentStreamCard v-for="a in agents" :key="a.index" :agent="{ ...a, showCasesAsList: true }">
          <template #time>
            <span v-if="agentSeconds(a) != null" class="agent-time">· ⏱ {{ formatDuration(agentSeconds(a)) }}</span>
          </template>
        </AgentStreamCard>
      </el-collapse>
    </div>

    <!-- 单批（无模块拆分）时的全局流式兜底 -->
    <div v-if="isGenerating && streamText && !agents.length" class="stream-output">{{ streamText }}</div>

    <!-- 评审 agent 卡片区：每个模块分组一张卡，实时流式展示评审过程（保留/删除判断）。 -->
    <div v-if="reviewAgents.length" class="agent-area">
      <div class="phase-label">🔍 测试专家分模块并行评审</div>
      <el-collapse v-model="openReviewAgents">
        <AgentStreamCard v-for="a in reviewAgents" :key="a.index" :agent="{ ...a, failedMessage: '该模块评审失败，已跳过（默认全部保留）' }">
          <template #time>
            <span v-if="agentSeconds(a) != null" class="agent-time">· ⏱ {{ formatDuration(agentSeconds(a)) }}</span>
          </template>
        </AgentStreamCard>
      </el-collapse>
    </div>

    <!-- 补充 agent 卡片区：被删场景/遗漏场景各一张卡，实时流式展示补充用例的生成。 -->
    <div v-if="supplementAgents.length" class="agent-area">
      <div class="phase-label">➕ 分模块并行补充遗漏场景</div>
      <el-collapse v-model="openSupplementAgents">
        <AgentStreamCard v-for="a in supplementAgents" :key="a.index" :agent="{ ...a, failedMessage: '该组补充失败，已跳过' }">
          <template #time>
            <span v-if="agentSeconds(a) != null" class="agent-time">· ⏱ {{ formatDuration(agentSeconds(a)) }}</span>
          </template>
        </AgentStreamCard>
      </el-collapse>
    </div>

    <el-tag v-if="knowledgeSummary !== '无'" size="small" type="info" style="margin:8px 0">引用知识：{{ knowledgeSummary }}</el-tag>
    <div v-if="hasCases" class="final-cases-title">最终用例（评审+补充后，共 {{ cases.length }} 条）</div>
    <div v-for="(c, idx) in cases" :key="idx" style="margin-bottom:8px">
      <el-collapse>
        <el-collapse-item>
          <template #title>
            <span style="font-weight:bold;color:#409EFF">#{{ idx + 1 }}</span>
            <el-tag v-if="c.priority" size="small" :type="priorityTagType(c.priority)" style="margin:0 8px">{{ c.priority }}</el-tag>
            <el-tag v-if="c.origin === 'supplement'" size="small" type="primary" effect="plain" style="margin-right:8px">补充</el-tag>
            <span>{{ c.title }}</span>
          </template>
          <div v-if="c.precondition" style="margin-bottom:6px;font-size:13px">前置：{{ c.precondition }}</div>
          <div v-if="c.steps" style="margin-bottom:6px;font-size:13px;white-space:pre-wrap">步骤：{{ typeof c.steps === 'string' ? c.steps : JSON.stringify(c.steps) }}</div>
          <div v-if="c.expected_result" style="font-size:13px;color:#67C23A">预期：{{ c.expected_result }}</div>
        </el-collapse-item>
      </el-collapse>
    </div>
    <el-empty v-if="!isGenerating && !hasCases" description="输入需求后点击生成" />
  </el-card>
</template>

<style scoped>
.results-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.stream-output { margin-top: 10px; padding: 10px 12px; background: #1e1e1e; color: #d4d4d4; border-radius: 6px; font-family: 'SFMono-Regular', Menlo, Consolas, monospace; font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; max-height: 360px; overflow-y: auto; }
.stream-output.thinking { background: #2a2a2a; color: #9aa0a6; font-style: italic; }
.thinking-badge { font-style: normal; color: #c8a95a; margin-bottom: 6px; font-weight: 600; }
.module-list { margin: 8px 0; display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.module-list-label { font-size: 13px; color: #606266; font-weight: 600; }
.module-tag { margin: 0; }
.agent-area { margin: 10px 0; }
.phase-label { font-size: 13px; font-weight: 600; color: #606266; margin: 6px 0; }
.agent-time { color: #409EFF; }
.final-cases-title { font-size: 14px; font-weight: 600; color: #303133; margin: 12px 0 8px; }
.total-time { font-weight: 400; font-size: 13px; color: #409EFF; }
</style>
