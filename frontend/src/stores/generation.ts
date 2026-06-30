import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { generationApi, type CaseRecord, type KnowledgeMatches } from '@/api/generation'
import { kbApi } from '@/api/knowledge'
import type { KnowledgeBase } from '@/types/project'
import type { GeneratedTestCase } from '@/types/testCase'

export const useGenerationStore = defineStore('generation', () => {
  // 知识库列表
  const kbs = ref<KnowledgeBase[]>([])

  // 输入表单（提取到 store，切换页面后回来仍保留）
  const selectedKbs = ref<string[]>([])
  const requirementText = ref('')
  const batchName = ref('')
  const inputMode = ref<'text' | 'file'>('text')
  const isParsing = ref(false)
  const parsedFilename = ref('')
  const tabActive = ref<'generate' | 'history'>('generate')

  // 生成状态（核心：脱离视图组件生命周期，切换页面/tab 不中断、不丢失）
  const isGenerating = ref(false)
  const genProgress = ref('')
  const streamText = ref('')
  const cases = ref<GeneratedTestCase[]>([])
  const knowledgeCounts = ref<Record<string, number>>({})
  const knowledgeMatches = ref<KnowledgeMatches>({})
  const validationWarnings = ref<any[]>([])

  // 当前后台任务（刷新后用于重连续看）
  const taskId = ref<string | null>(null)
  const taskTitle = ref('')

  // 历史记录
  const history = ref<CaseRecord[]>([])

  let kbsLoaded = false

  async function fetchKbs(force = false) {
    if (kbsLoaded && !force) return
    kbs.value = await kbApi.list()
    kbsLoaded = true
  }

  async function fetchHistory() {
    try {
      history.value = await generationApi.listCases()
    } catch {
      ElMessage.error('加载生成历史失败')
    }
  }

  async function parsePrd(file: File) {
    isParsing.value = true
    parsedFilename.value = ''
    try {
      const data = await generationApi.parsePrd(file)
      requirementText.value = data.text
      parsedFilename.value = data.filename
      ElMessage.success(`解析 ${data.length} 字`)
    } catch (e: any) {
      ElMessage.error(e.message)
    } finally {
      isParsing.value = false
    }
  }

  // 处理单个 SSE 事件，更新各状态。首发与重连共用。
  function _handleEvent(event: Parameters<Parameters<typeof generationApi.streamTask>[1]>[0], onComplete: () => void) {
    if (event.type === 'progress') {
      genProgress.value = event.message
      // 进入修正阶段时清空首轮输出，避免两轮文本拼接在一起
      if (event.stage === 'correcting') streamText.value = ''
    } else if (event.type === 'chunk') {
      streamText.value += event.text
    } else if (event.type === 'complete') {
      cases.value = event.cases || []
      knowledgeCounts.value = event.knowledge_used || {}
      knowledgeMatches.value = event.knowledge_matches || {}
      validationWarnings.value = (event.validation_warnings as any[]) || []
      onComplete()
    } else if (event.type === 'error') {
      throw new Error(event.message)
    }
  }

  // 连接（或重连）到指定任务，消费其事件流直到结束。
  async function _consume(id: string, replay: boolean) {
    isGenerating.value = true
    if (!replay) {
      cases.value = []
      knowledgeCounts.value = {}
      knowledgeMatches.value = {}
      validationWarnings.value = []
      genProgress.value = '正在准备...'
      streamText.value = ''
    }
    let completed = false
    try {
      await generationApi.streamTask(id, (event) => _handleEvent(event, () => { completed = true }))
      if (completed) {
        ElMessage.success(`生成完成，共 ${cases.value.length} 条`)
      }
    } catch (e: any) {
      ElMessage.error(e.message)
    } finally {
      isGenerating.value = false
      genProgress.value = ''
      taskId.value = null
      fetchHistory()
    }
  }

  async function generate() {
    if (!requirementText.value.trim()) {
      ElMessage.warning('请输入需求')
      return
    }
    if (isGenerating.value) return

    try {
      const task = await generationApi.startTask({
        kb_ids: selectedKbs.value,
        requirement_text: requirementText.value,
        batch_name: batchName.value,
      })
      taskId.value = task.task_id
      taskTitle.value = task.title
      await _consume(task.task_id, false)
    } catch (e: any) {
      ElMessage.error(e.message)
      isGenerating.value = false
    }
  }

  // 应用加载时调用：若后台仍有运行中的任务，自动重连续看实时进度。
  async function restoreActiveTask() {
    if (isGenerating.value) return
    try {
      const active = await generationApi.activeTasks()
      if (!active.length) return
      const task = active[0]
      taskId.value = task.task_id
      taskTitle.value = task.title
      await _consume(task.task_id, true)
    } catch {
      // 无活动任务或接口不可用时静默忽略
    }
  }

  return {
    kbs,
    selectedKbs,
    requirementText,
    batchName,
    inputMode,
    isParsing,
    parsedFilename,
    tabActive,
    isGenerating,
    genProgress,
    streamText,
    cases,
    knowledgeCounts,
    knowledgeMatches,
    validationWarnings,
    taskId,
    taskTitle,
    history,
    fetchKbs,
    fetchHistory,
    parsePrd,
    generate,
    restoreActiveTask,
  }
})
