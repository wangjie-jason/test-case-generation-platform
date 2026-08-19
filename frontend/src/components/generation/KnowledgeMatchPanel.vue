<script setup lang="ts">
import { computed } from 'vue'
import { useKnowledgeMatches, type KnowledgeCounts } from '@/composables/useKnowledgeMatches'
import type { KnowledgeMatches } from '@/api/generation'

const props = defineProps<{
  isGenerating: boolean
  genProgress: string
  hasCases: boolean
  knowledgeCounts: KnowledgeCounts
  knowledgeMatches: KnowledgeMatches
}>()

// 包一层 ref，composable 内部统一用 ref.value 访问。两边实现不一致时 ref 更稳。
const counts = computed(() => props.knowledgeCounts)
const matches = computed(() => props.knowledgeMatches)
const { summary, groups, hasAny, title, description } = useKnowledgeMatches(counts, matches)
</script>

<template>
  <el-card>
    <template #header>
      <div class="results-toolbar">
        <span>检索预警命中知识</span>
        <el-tag v-if="summary !== '无'" size="small" type="warning">{{ summary }}</el-tag>
      </div>
    </template>
    <!-- 命中知识内容区：设最大高度，命中过多时栏内滚动，避免撑长整个页面 -->
    <div class="knowledge-body">
      <el-alert v-if="isGenerating && !hasAny" :title="genProgress || '正在检索知识库并生成用例...'" type="info" :closable="false" />
      <template v-else-if="hasAny">
        <div v-for="group in groups" :key="group.key" class="match-group">
          <div class="match-group-title">
            <span>{{ group.title }}</span>
            <el-tag size="small" effect="plain">{{ group.items.length || knowledgeCounts[group.countKey] || 0 }}</el-tag>
          </div>
          <div v-for="(item, idx) in group.items" :key="`${group.key}-${idx}`" class="match-item">
            <div class="match-title">{{ title(group.key, item) }}</div>
            <div v-if="description(group.key, item)" class="match-desc">{{ description(group.key, item) }}</div>
          </div>
        </div>
      </template>
      <el-empty v-else :description="hasCases ? '未命中知识库内容' : '生成后显示命中的字段、规则、缺陷等知识'" />
    </div>
  </el-card>
</template>

<style scoped>
.results-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
/* 命中知识过多时栏内滚动，不撑长整个页面 */
.knowledge-body { max-height: 60vh; overflow-y: auto; padding-right: 4px; }
.match-group { margin-bottom: 14px; }
.match-group-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 13px; font-weight: 600; color: #303133; }
.match-item { padding: 8px 10px; margin-bottom: 8px; border: 1px solid #ebeef5; border-radius: 8px; background: #fafafa; }
.match-title { font-size: 13px; font-weight: 600; color: #409EFF; }
.match-desc { margin-top: 4px; font-size: 12px; line-height: 1.5; color: #606266; white-space: pre-wrap; word-break: break-word; }
</style>
