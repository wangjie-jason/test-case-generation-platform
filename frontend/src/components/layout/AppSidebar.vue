<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { HomeFilled, Document, Tickets, Monitor } from '@element-plus/icons-vue'

const route = useRoute(); const router = useRouter()
const items = [
  { path: '/', title: '看板', icon: HomeFilled },
  { path: '/generate', title: '用例生成', icon: Tickets },
  { path: '/review', title: '审核标注', icon: Monitor },
  { path: '/knowledge', title: '知识库', icon: Document },
]
const active = computed(() => {
  const p = route.path
  if (p === '/' || p === '/stats') return '/'
  if (p.includes('/knowledge')) return '/knowledge'
  if (p.includes('/generate')) return '/generate'
  if (p.includes('/review')) return '/review'
  return ''
})
</script>
<template>
  <nav class="app-sidebar">
    <el-menu :default-active="active" @select="(path: string) => router.push(path)">
      <el-menu-item v-for="item in items" :key="item.path" :index="item.path">
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ item.title }}</span>
      </el-menu-item>
    </el-menu>
  </nav>
</template>
<style scoped>
.app-sidebar { width: 200px; flex-shrink: 0; background: #fff; border-right: 1px solid #e4e7ed; overflow-y: auto; }
</style>
