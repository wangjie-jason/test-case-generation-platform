<script setup lang="ts">
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import { useGenerationStore } from '@/stores/generation'

const router = useRouter()
const store = useGenerationStore()
const { anyRunning, runningCount, genProgress, taskTitle } = storeToRefs(store)

// 应用加载/刷新后，若后台仍有本客户端运行中的生成任务，自动重连以便继续观看进度
onMounted(() => { store.restoreActiveTasks() })

function goWatch() {
  store.tabActive = 'generate'
  router.push('/generate')
}
</script>

<template>
  <header class="app-header">
    <h1 class="header-title">Test Case Generation Platform</h1>
    <div
      v-if="anyRunning"
      class="gen-indicator"
      title="点击查看生成进度"
      @click="goWatch"
    >
      <el-icon class="spin"><Loading /></el-icon>
      <span class="gen-text">
        <template v-if="runningCount > 1">{{ runningCount }} 个任务生成中</template>
        <template v-else>{{ taskTitle || '用例生成中' }}：{{ genProgress || '生成中...' }}</template>
      </span>
      <span class="gen-link">查看</span>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  padding: 0 20px;
  height: 56px;
  flex-shrink: 0;
}
.header-title {
  font-size: 18px;
  color: #303133;
  margin: 0;
  font-weight: 600;
}
.gen-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 50%;
  padding: 6px 14px;
  border-radius: 16px;
  background: #ecf5ff;
  border: 1px solid #d9ecff;
  color: #409eff;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s;
}
.gen-indicator:hover {
  background: #d9ecff;
}
.gen-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.gen-link {
  font-weight: 600;
  flex-shrink: 0;
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
