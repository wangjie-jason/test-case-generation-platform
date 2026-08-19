<script setup lang="ts">
import { Loading } from '@element-plus/icons-vue'
import { priorityTagType } from '@/utils/priority'
import { renderSteps } from '@/utils/renderSteps'
import type { AgentState } from '@/stores/generation'

withDefaults(defineProps<{
  agent: AgentState
  /** 运行中的 meta 文案：生成「生成中…」、评审「评审中…」、补充「补充中…」。 */
  runningMessage?: string
  /** 失败时展开区里的解释文案。折叠头 meta 固定显示「失败」，长文案不挤掉模块名。 */
  failedMessage?: string
  /** 完成但一条用例都没产出时的占位文案（仅 showCasesAsList 生效）。 */
  emptyMessage?: string
  /** 生成阶段：完成后把流式文本换成解析好的用例列表，meta 显示「N 条」。
   *  评审 / 补充阶段为 false：完成后仍展示流文本，meta 显示 agent.summary。 */
  showCasesAsList?: boolean
}>(), {
  runningMessage: '生成中…',
  failedMessage: '该模块生成失败，已跳过（其余模块不受影响）',
  emptyMessage: '该模块未产出用例',
  showCasesAsList: false,
})
</script>

<template>
  <el-collapse-item :name="agent.index">
    <template #title>
      <el-icon v-if="agent.status === 'running'" class="spin agent-ico"><Loading /></el-icon>
      <span v-else-if="agent.status === 'done'" class="agent-ico done">✓</span>
      <span v-else class="agent-ico failed">✕</span>
      <span class="agent-name">{{ agent.module }}</span>
      <span class="agent-meta">
        <template v-if="agent.status === 'running'">{{ runningMessage }}</template>
        <template v-else-if="agent.status === 'failed'">失败</template>
        <template v-else-if="showCasesAsList">{{ agent.cases.length }} 条</template>
        <template v-else>{{ agent.summary }}</template>
        <slot name="time" />
      </span>
    </template>
    <!-- 完成：可选展示解析好的用例列表（生成阶段用） -->
    <template v-if="agent.status === 'done' && showCasesAsList">
      <div v-if="!agent.cases.length" class="agent-empty">{{ emptyMessage }}</div>
      <div v-for="(c, ci) in agent.cases" :key="ci" class="agent-case">
        <el-tag v-if="c.priority" size="small" :type="priorityTagType(c.priority)" effect="plain" style="margin-right:6px">{{ c.priority }}</el-tag>
        <strong>{{ c.title }}</strong>
        <div v-if="c.precondition" class="agent-case-line">前置：{{ c.precondition }}</div>
        <div v-if="c.steps" class="agent-case-line" style="white-space:pre-wrap">步骤：{{ renderSteps(c.steps) }}</div>
        <div v-if="c.expected_result" class="agent-case-line" style="color:#67C23A">预期：{{ c.expected_result }}</div>
      </div>
    </template>
    <!-- 失败 -->
    <div v-else-if="agent.status === 'failed'" class="agent-empty">{{ failedMessage }}</div>
    <!-- 生成中 / 评审 / 补充：流式展示 -->
    <template v-else>
      <div v-if="agent.streamText" class="stream-output">{{ agent.streamText }}</div>
      <div v-else-if="agent.thinkText" class="stream-output thinking">
        <div class="thinking-badge">🤔 深度思考中…</div>{{ agent.thinkText }}
      </div>
      <div v-else class="stream-output thinking">🤔 深度思考中…</div>
    </template>
  </el-collapse-item>
</template>

<style scoped>
.agent-ico { flex-shrink: 0; width: 18px; text-align: center; margin-right: 6px; }
.agent-ico.done { color: #67C23A; font-weight: bold; }
.agent-ico.failed { color: #F56C6C; font-weight: bold; }
.agent-name { font-weight: 600; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-meta { flex-shrink: 0; font-size: 12px; color: #909399; margin-left: 8px; }
.agent-empty { font-size: 13px; color: #909399; padding: 6px 0; }
.agent-case { padding: 6px 0; border-bottom: 1px solid #f0f0f0; font-size: 13px; }
.agent-case-line { color: #606266; margin-top: 2px; }
.stream-output { margin-top: 10px; padding: 10px 12px; background: #1e1e1e; color: #d4d4d4; border-radius: 6px; font-family: 'SFMono-Regular', Menlo, Consolas, monospace; font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; max-height: 360px; overflow-y: auto; }
.stream-output.thinking { background: #2a2a2a; color: #9aa0a6; font-style: italic; }
.thinking-badge { font-style: normal; color: #c8a95a; margin-bottom: 6px; font-weight: 600; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
</style>
