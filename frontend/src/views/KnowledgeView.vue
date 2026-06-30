<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import { ElMessage, ElMessageBox } from 'element-plus'
import FieldDictTable from '@/components/knowledge/FieldDictTable.vue'
import BusinessRuleTable from '@/components/knowledge/BusinessRuleTable.vue'
import StateMachineTable from '@/components/knowledge/StateMachineTable.vue'
import TermMappingTable from '@/components/knowledge/TermMappingTable.vue'
import PrdDocumentPanel from '@/components/knowledge/PrdDocumentPanel.vue'
import DefectRecordPanel from '@/components/knowledge/DefectRecordPanel.vue'

const store = useKnowledgeStore()
const selectedKbId = ref<string | null>(null)
const selectedKbName = ref('')
const activeTab = ref('prd-docs')
const createDialog = ref(false)
const newKbName = ref('')

const tabs = [
  { name: 'prd-docs', label: 'PRD文档' }, { name: 'defects', label: '缺陷记录' },
  { name: 'field-dicts', label: '字段字典' }, { name: 'business-rules', label: '业务规则' },
  { name: 'state-machines', label: '状态机' }, { name: 'term-mappings', label: '术语映射' },
]

onMounted(() => store.fetchKbs())

async function handleCreateKb() {
  if (!newKbName.value.trim()) return
  const kb = await store.createKb({ name: newKbName.value })
  createDialog.value = false; newKbName.value = ''
  selectKb(kb.id, kb.name)
  ElMessage.success('知识库创建成功')
}

async function handleDeleteKb(id: string) {
  try { await ElMessageBox.confirm('删除知识库及所有数据？', '警告', { type: 'warning' }); await store.deleteKb(id); if (selectedKbId.value === id) selectedKbId.value = null; ElMessage.success('已删除') }
  catch {}
}

async function selectKb(id: string, name: string) {
  selectedKbId.value = null
  store.clearDetails()
  selectedKbName.value = name
  await store._fetch(id)
  selectedKbId.value = id
}
</script>

<template>
  <div class="kb-view">
    <!-- 知识库列表 -->
    <template v-if="!selectedKbId">
      <div class="kb-header"><h2>知识库</h2><el-button type="primary" @click="createDialog = true">+ 新建知识库</el-button></div>
      <el-row :gutter="16" v-if="store.kbs.length">
        <el-col v-for="kb in store.kbs" :key="kb.id" :span="8">
          <el-card shadow="hover" class="kb-card" @click="selectKb(kb.id, kb.name)">
            <div class="kb-card-header">
              <span class="kb-card-name">{{ kb.name }}</span>
              <el-button type="danger" link @click.stop="handleDeleteKb(kb.id)"><el-icon><Delete /></el-icon></el-button>
            </div>
            <div class="kb-card-desc">{{ kb.description || '暂无描述' }}</div>
            <div class="kb-card-meta">{{ kb.created_at?.slice(0, 10) }}</div>
          </el-card>
        </el-col>
      </el-row>
      <el-empty v-else description="暂无知识库，点击上方按钮创建" />
    </template>

    <!-- 知识库详情 -->
    <template v-else>
      <div class="kb-detail-header">
        <el-button class="kb-back-button" link @click="selectedKbId = null"><el-icon><ArrowLeft /></el-icon> 返回</el-button>
        <h2 class="kb-detail-title">{{ selectedKbName }}</h2>
      </div>
      <el-tabs v-model="activeTab">
        <el-tab-pane v-for="t in tabs" :key="t.name" :label="t.label" :name="t.name" />
      </el-tabs>
      <div v-if="store.loadingDetails" style="padding:40px;text-align:center;color:#909399">知识库加载中...</div>
      <template v-else>
        <FieldDictTable v-if="activeTab === 'field-dicts'" :kb-id="selectedKbId" />
        <BusinessRuleTable v-if="activeTab === 'business-rules'" :kb-id="selectedKbId" />
        <StateMachineTable v-if="activeTab === 'state-machines'" :kb-id="selectedKbId" />
        <TermMappingTable v-if="activeTab === 'term-mappings'" :kb-id="selectedKbId" />
        <PrdDocumentPanel v-if="activeTab === 'prd-docs'" :kb-id="selectedKbId" />
        <DefectRecordPanel v-if="activeTab === 'defects'" :kb-id="selectedKbId" />
      </template>
    </template>

    <el-dialog v-model="createDialog" title="新建知识库" width="420px">
      <el-form @submit.prevent="handleCreateKb">
        <el-form-item label="名称" required><el-input v-model="newKbName" placeholder="如 实时视频监控" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="createDialog = false">取消</el-button><el-button type="primary" @click="handleCreateKb">创建</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.kb-view { max-width: 1024px; margin: 0 auto; }
.kb-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.kb-card { cursor: pointer; margin-bottom: 16px; min-height: 120px; }
.kb-card:hover { border-color: #409EFF; }
.kb-card-header { display: flex; justify-content: space-between; align-items: center; }
.kb-card-name { font-size: 16px; font-weight: 600; }
.kb-card-desc { margin-top: 8px; color: #909399; font-size: 13px; }
.kb-card-meta { margin-top: 12px; font-size: 12px; color: #c0c4cc; }
.kb-detail-header { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; margin-bottom: 16px; }
.kb-back-button { padding: 0; }
.kb-detail-title { margin: 0; font-size: 24px; font-weight: 600; color: #303133; }
</style>
