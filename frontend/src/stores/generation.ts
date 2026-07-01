import { defineStore } from 'pinia'
import { ref, reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { generationApi, type CaseRecord, type KnowledgeMatches, type GenerateStreamEvent } from '@/api/generation'
import { kbApi } from '@/api/knowledge'
import type { KnowledgeBase } from '@/types/project'
import type { GeneratedTestCase } from '@/types/testCase'

// 单个生成任务的前端状态。多个任务并行时各自独立，互不影响。
interface TaskState {
  taskId: string
  title: string
  status: 'running' | 'done' | 'error'
  genProgress: string
  streamText: string
  cases: GeneratedTestCase[]
  knowledgeCounts: Record<string, number>
  knowledgeMatches: KnowledgeMatches
  validationWarnings: any[]
}

function newTaskState(taskId: string, title: string): TaskState {
  return {
    taskId, title, status: 'running',
    genProgress: '正在准备...', streamText: '',
    cases: [], knowledgeCounts: {}, knowledgeMatches: {}, validationWarnings: [],
  }
}

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

  // 多任务：taskId -> 任务状态。并行生成的核心。
  const tasks = reactive(new Map<string, TaskState>())
  // 当前在结果区查看的任务 id（不影响其它任务继续在后台跑）
  const activeTaskId = ref<string | null>(null)

  // 历史记录
  const history = ref<CaseRecord[]>([])

  let kbsLoaded = false

  // ——— 兼容旧模板：以下计算属性指向「当前查看的任务」———
  const current = computed<TaskState | null>(() => activeTaskId.value ? tasks.get(activeTaskId.value) ?? null : null)
  const genProgress = computed(() => current.value?.genProgress ?? '')
  const streamText = computed(() => current.value?.streamText ?? '')
  const cases = computed(() => current.value?.cases ?? [])
  const knowledgeCounts = computed(() => current.value?.knowledgeCounts ?? {})
  const knowledgeMatches = computed(() => current.value?.knowledgeMatches ?? {})
  const validationWarnings = computed(() => current.value?.validationWarnings ?? [])
  const taskTitle = computed(() => current.value?.title ?? '')
  // 当前查看的任务是否在生成中（用于结果区的加载态）
  const isGenerating = computed(() => current.value?.status === 'running')

  // 任务列表（最近的在前），供多任务 UI 展示
  const taskList = computed(() => Array.from(tasks.values()).reverse())
  // 是否有任意任务在运行（页头指示器用）
  const runningCount = computed(() => Array.from(tasks.values()).filter(t => t.status === 'running').length)
  const anyRunning = computed(() => runningCount.value > 0)

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

  // 处理单个 SSE 事件，更新对应任务的状态。首发与重连共用。
  function _handleEvent(t: TaskState, event: GenerateStreamEvent, onComplete: () => void) {
    if (event.type === 'progress') {
      t.genProgress = event.message
      // 进入补充阶段时清空首轮流式文本，避免与补充用例的输出拼接在一起
      if (event.stage === 'supplementing') t.streamText = ''
    } else if (event.type === 'chunk') {
      t.streamText += event.text
    } else if (event.type === 'complete') {
      t.cases = event.cases || []
      t.knowledgeCounts = event.knowledge_used || {}
      t.knowledgeMatches = event.knowledge_matches || {}
      t.validationWarnings = (event.validation_warnings as any[]) || []
      onComplete()
    } else if (event.type === 'error') {
      throw new Error(event.message)
    }
  }

  // 连接（或重连）到指定任务，消费其事件流直到结束。不阻塞其它任务。
  async function _consume(t: TaskState) {
    let completed = false
    try {
      await generationApi.streamTask(t.taskId, (event) => _handleEvent(t, event, () => { completed = true }))
      t.status = 'done'
      if (completed) {
        ElMessage.success(`「${t.title}」生成完成，共 ${t.cases.length} 条`)
      }
    } catch (e: any) {
      t.status = 'error'
      t.genProgress = ''
      ElMessage.error(`「${t.title}」${e.message}`)
    } finally {
      fetchHistory()
    }
  }

  async function generate() {
    if (!requirementText.value.trim()) {
      ElMessage.warning('请输入需求')
      return
    }
    try {
      const summary = await generationApi.startTask({
        kb_ids: selectedKbs.value,
        requirement_text: requirementText.value,
        batch_name: batchName.value,
      })
      const t = newTaskState(summary.task_id, summary.title)
      tasks.set(t.taskId, t)
      activeTaskId.value = t.taskId  // 新任务自动成为查看目标
      // 后台并发消费，不 await——允许立即发起下一个生成
      _consume(t)
    } catch (e: any) {
      ElMessage.error(e.message)
    }
  }

  // 选择在结果区查看某个任务
  function viewTask(taskId: string) {
    if (tasks.has(taskId)) activeTaskId.value = taskId
  }

  // 从列表中移除一个已结束的任务（仅前端展示，不影响后端/历史）
  function dismissTask(taskId: string) {
    const t = tasks.get(taskId)
    if (t && t.status === 'running') return // 运行中不允许移除
    tasks.delete(taskId)
    if (activeTaskId.value === taskId) {
      activeTaskId.value = taskList.value[0]?.taskId ?? null
    }
  }

  // 应用加载时调用：重连本客户端所有运行中的任务（多浏览器隔离由后端按 client_id 过滤）。
  async function restoreActiveTasks() {
    try {
      const active = await generationApi.activeTasks()
      for (const summary of active) {
        if (tasks.has(summary.task_id)) continue
        const t = newTaskState(summary.task_id, summary.title)
        tasks.set(t.taskId, t)
        if (!activeTaskId.value) activeTaskId.value = t.taskId
        _consume(t)  // 各自重连，互不阻塞
      }
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
    // 多任务
    taskList,
    activeTaskId,
    runningCount,
    anyRunning,
    // 当前查看任务的兼容字段
    isGenerating,
    genProgress,
    streamText,
    cases,
    knowledgeCounts,
    knowledgeMatches,
    validationWarnings,
    taskTitle,
    history,
    fetchKbs,
    fetchHistory,
    parsePrd,
    generate,
    viewTask,
    dismissTask,
    restoreActiveTasks,
  }
})
