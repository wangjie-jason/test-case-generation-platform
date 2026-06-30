<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { generationApi, type StatsOverview } from '@/api/generation'

const stats = ref<StatsOverview>({
  total_cases: 0,
  reviewed_cases: 0,
  approved_cases: 0,
  rejected_cases: 0,
  usability_rate: 0,
  hallucination_distribution: {},
  generation_count: 0,
})
const loading = ref(false)

const hallucinationLabels: Record<string, string> = {
  field_hallucination: '字段幻觉', rule_hallucination: '规则幻觉',
  context_missing: '上下文缺失', style_mismatch: '风格不一致',
}

onMounted(async () => {
  loading.value = true
  try { stats.value = await generationApi.statsOverview() }
  catch { ElMessage.error('加载失败') }
  finally { loading.value = false }
})

const hallucinationItems = computed(() => {
  return Object.entries(stats.value.hallucination_distribution).map(([key, count]) => ({ name: hallucinationLabels[key] || key, value: count }))
})

function hallucinationPercent(count: number) {
  if (stats.value.reviewed_cases <= 0) return 0
  return Math.round((count / stats.value.reviewed_cases) * 100)
}
</script>

<template>
  <div class="stats-view" v-loading="loading">
    <h2 class="page-title">统计分析</h2>

    <el-row :gutter="20" type="flex" class="stat-row">
      <el-col :span="6">
        <div class="stat-card"><div class="stat-num">{{ stats.total_cases || 0 }}</div><div class="stat-label">生成用例总数</div></div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card"><div class="stat-num">{{ stats.reviewed_cases || 0 }}</div><div class="stat-label">已审核</div></div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card"><div class="stat-num">{{ stats.approved_cases || 0 }}<span class="stat-pct"> / {{ stats.usability_rate || 0 }}%</span></div><div class="stat-label">通过</div></div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card"><div class="stat-num">{{ stats.generation_count || 0 }}</div><div class="stat-label">生成批次</div></div>
      </el-col>
    </el-row>

    <el-row :gutter="20" type="flex" style="margin-top:24px">
      <el-col :span="12">
        <el-card header="幻觉分布" shadow="never" class="mid-card">
          <div v-if="!hallucinationItems.length" style="text-align:center;padding:40px;color:#909399">暂无疑似幻觉用例，质量良好</div>
          <div v-for="item in hallucinationItems" :key="item.name" class="hall-item" v-else>
            <span class="hall-name">{{ item.name }}</span>
            <div class="hall-bar-wrap"><div class="hall-bar" :style="{width: hallucinationPercent(item.value) + '%'}"></div></div>
            <span class="hall-num">{{ item.value }} 条</span>
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card header="质量概览" shadow="never" class="mid-card">
          <div class="quality-circle">
            <div class="quality-num" :style="{color: stats.usability_rate >= 85 ? '#67C23A' : '#E6A23C'}">{{ stats.usability_rate || 0 }}%</div>
            <div class="quality-sub">用例可用率</div>
          </div>
          <el-progress :percentage="stats.usability_rate || 0" :color="stats.usability_rate >= 85 ? '#67C23A' : '#E6A23C'" :stroke-width="16" />
          <div class="quality-target">{{ stats.usability_rate >= 85 ? '✅ 已达标' : '⚠️ 继续优化知识库' }}（目标 ≥ 85%）</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" type="flex" style="margin-top:32px">
      <el-col :span="8">
        <el-card shadow="never" class="feat-card"><template #header><span class="feat-title">知识库管理</span></template><p class="feat-desc">管理字段字典、业务规则、状态机和术语映射。支持 PRD 上传和缺陷 Excel 导入，构建项目级测试知识库。</p></el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never" class="feat-card"><template #header><span class="feat-title">智能生成</span></template><p class="feat-desc">上传 PRD 或输入需求描述，AI 基于知识库自动生成测试用例，格式对齐团队模板。</p></el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never" class="feat-card"><template #header><span class="feat-title">持续优化</span></template><p class="feat-desc">审核标注用例质量，系统自动识别知识缺口。可用率目标 ≥ 85%，质量持续提升。</p></el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.stats-view { max-width: 1024px; margin: 0 auto; }
.page-title { margin: 0 0 20px 0; font-size: 20px; }
.stat-row { margin: 0; }
.stat-card { background: #fff; border-radius: 8px; padding: 28px 20px; text-align: center; border: 1px solid #ebeef5; height: 110px; display: flex; flex-direction: column; justify-content: center; }
.stat-num { font-size: 28px; font-weight: 700; color: #303133; }
.stat-pct { font-size: 14px; color: #67C23A; font-weight: 400; }
.stat-label { margin-top: 6px; font-size: 13px; color: #909399; }
.hall-item { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.hall-name { width: 72px; font-size: 13px; color: #606266; flex-shrink: 0; }
.hall-bar-wrap { flex: 1; background: #f0f0f0; border-radius: 4px; height: 10px; overflow: hidden; }
.hall-bar { background: #E6A23C; height: 100%; border-radius: 4px; min-width: 2px; transition: width .3s; }
.hall-num { font-size: 12px; color: #909399; width: 40px; flex-shrink: 0; text-align: right; }
.quality-circle { text-align: center; padding: 12px 0 20px; }
.quality-num { font-size: 52px; font-weight: 700; }
.quality-sub { font-size: 14px; color: #909399; margin-top: 4px; }
.quality-target { margin-top: 10px; text-align: center; font-size: 13px; color: #909399; }
.mid-card { height: 100%; }
.feat-card { height: 100%; }
.feat-title { font-weight: 600; font-size: 15px; }
.feat-desc { color: #909399; font-size: 13px; line-height: 1.7; margin: 0; }
</style>
