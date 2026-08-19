<script setup lang="ts">
defineProps<{
  totalCases: number
  totalReviewed: number
  totalApproved: number
  usabilityRate: number
}>()
</script>

<template>
  <div class="stats-bar">
    <el-statistic title="总用例" :value="totalCases" />
    <el-statistic title="已审核" :value="totalReviewed" />
    <el-statistic title="通过" :value="totalApproved" />
    <!-- el-statistic 只有 title/prefix/suffix 三个 slot，没有 default——
         原来写 #default 会被整个丢弃，又没传 value，于是恒显示 0 -->
    <el-statistic title="可用率" :value="usabilityRate"
                  :value-style="{ color: usabilityRate >= 85 ? '#67C23A' : '#E6A23C' }">
      <template #suffix><span :style="{color: usabilityRate >= 85 ? '#67C23A' : '#E6A23C'}">%</span></template>
    </el-statistic>
  </div>
</template>

<style scoped>
.stats-bar { display: flex; gap: 40px; margin: 20px 0; padding: 16px; background: #fff; border-radius: 8px; }
</style>
