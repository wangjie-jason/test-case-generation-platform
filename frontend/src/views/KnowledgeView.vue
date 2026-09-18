<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import type { KnowledgeBase } from '@/types/project'
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
const formVisible = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const editingId = ref<string | null>(null)
const formName = ref('')
const formDesc = ref('')
const formVisibility = ref<'team' | 'personal'>('team')
// 当前进入详情的知识库（用于判断只读：引用他人团队库时只能看不能改）。
const selectedKb = ref<KnowledgeBase | null>(null)

const tabs = [
  { name: 'prd-docs', label: 'PRD文档' }, { name: 'defects', label: '缺陷记录' },
  { name: 'field-dicts', label: '字段字典' }, { name: 'business-rules', label: '业务规则' },
  { name: 'state-machines', label: '状态机' }, { name: 'term-mappings', label: '术语映射' },
]

onMounted(() => store.fetchKbs())

function openCreate() {
  formMode.value = 'create'; editingId.value = null
  formName.value = ''; formDesc.value = ''; formVisibility.value = 'team'
  formVisible.value = true
}

function openEdit(kb: KnowledgeBase) {
  formMode.value = 'edit'; editingId.value = kb.id
  formName.value = kb.name; formDesc.value = kb.description ?? ''
  formVisibility.value = kb.visibility
  formVisible.value = true
}

async function handleSubmit() {
  const name = formName.value.trim()
  if (!name) return
  const description = formDesc.value.trim()
  if (formMode.value === 'edit' && editingId.value) {
    await store.updateKb(editingId.value, {
      name, description: description || null, visibility: formVisibility.value,
    })
    ElMessage.success('知识库已更新')
  } else {
    const kb = await store.createKb({
      name, description: description || undefined, visibility: formVisibility.value,
    })
    selectKb(kb.id, kb.name, kb)
    ElMessage.success('知识库创建成功')
  }
  formVisible.value = false; formName.value = ''; formDesc.value = ''
}

async function handleDeleteKb(id: string) {
  try { await ElMessageBox.confirm('删除知识库及所有数据？', '警告', { type: 'warning' }); await store.deleteKb(id); if (selectedKbId.value === id) selectedKbId.value = null; ElMessage.success('已删除') }
  catch {}
}

async function selectKb(id: string, name: string, kb?: KnowledgeBase) {
  selectedKbId.value = null
  selectedKb.value = kb ?? store.kbs.find(k => k.id === id) ?? null
  store.clearDetails()
  selectedKbName.value = name
  await store._fetch(id)
  selectedKbId.value = id
}

function backToList() {
  selectedKbId.value = null
  selectedKb.value = null
  store.clearDetails()
}
</script>

<template>
  <div class="kb-view">
    <!-- 知识库列表 -->
    <template v-if="!selectedKbId">
      <div class="kb-header"><h2>知识库</h2><el-button type="primary" @click="openCreate">+ 新建知识库</el-button></div>
      <el-row :gutter="16" v-if="store.kbs.length">
        <el-col v-for="kb in store.kbs" :key="kb.id" :span="8">
          <el-card shadow="hover" class="kb-card" @click="selectKb(kb.id, kb.name, kb)">
            <div class="kb-card-header">
              <span class="kb-card-name">{{ kb.name }}</span>
              <span class="kb-card-actions">
                <template v-if="kb.can_manage">
                  <el-button type="primary" link @click.stop="openEdit(kb)"><el-icon><Edit /></el-icon></el-button>
                  <el-button type="danger" link @click.stop="handleDeleteKb(kb.id)"><el-icon><Delete /></el-icon></el-button>
                </template>
                <el-tag v-else size="small" type="info" effect="plain">只读</el-tag>
              </span>
            </div>
            <div class="kb-card-tags">
              <el-tag :type="kb.visibility === 'personal' ? 'warning' : 'success'" size="small">
                {{ kb.visibility === 'personal' ? '个人' : '团队' }}
              </el-tag>
              <span v-if="kb.visibility === 'team' && kb.owner_name" class="kb-card-owner">{{ kb.owner_name }} 创建</span>
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
        <el-button class="kb-back-button" link @click="backToList"><el-icon><ArrowLeft /></el-icon> 返回</el-button>
        <h2 class="kb-detail-title">
          {{ selectedKbName }}
          <el-tag :type="selectedKb?.visibility === 'personal' ? 'warning' : 'success'" size="small">
            {{ selectedKb?.visibility === 'personal' ? '个人' : '团队' }}
          </el-tag>
          <el-tag v-if="selectedKb && !selectedKb.can_manage" size="small" type="info" effect="plain">只读</el-tag>
        </h2>
      </div>
      <el-tabs v-model="activeTab">
        <el-tab-pane v-for="t in tabs" :key="t.name" :label="t.label" :name="t.name" />
      </el-tabs>
      <div v-if="store.loadingDetails" style="padding:40px;text-align:center;color:#909399">知识库加载中...</div>
      <template v-else>
        <FieldDictTable v-if="activeTab === 'field-dicts'" :kb-id="selectedKbId" :readonly="!selectedKb?.can_manage" />
        <BusinessRuleTable v-if="activeTab === 'business-rules'" :kb-id="selectedKbId" :readonly="!selectedKb?.can_manage" />
        <StateMachineTable v-if="activeTab === 'state-machines'" :kb-id="selectedKbId" :readonly="!selectedKb?.can_manage" />
        <TermMappingTable v-if="activeTab === 'term-mappings'" :kb-id="selectedKbId" :readonly="!selectedKb?.can_manage" />
        <PrdDocumentPanel v-if="activeTab === 'prd-docs'" :kb-id="selectedKbId" :readonly="!selectedKb?.can_manage" />
        <DefectRecordPanel v-if="activeTab === 'defects'" :kb-id="selectedKbId" :readonly="!selectedKb?.can_manage" />
      </template>
    </template>

    <el-dialog v-model="formVisible" :title="formMode === 'create' ? '新建知识库' : '编辑知识库'" width="420px">
      <el-form @submit.prevent="handleSubmit">
        <el-form-item label="名称" required><el-input v-model="formName" placeholder="如 实时视频监控" /></el-form-item>
        <el-form-item label="可见性">
          <el-radio-group v-model="formVisibility">
            <el-radio value="team" class="visibility-radio">
              团队：所有人可查看和引用，仅创建者/管理员可修改删除
            </el-radio>
            <el-radio value="personal" class="visibility-radio">
              个人：仅你自己可见和使用
            </el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="描述"><el-input v-model="formDesc" type="textarea" :rows="3" maxlength="1000" show-word-limit placeholder="这个知识库用来做什么（选填）" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="formVisible = false">取消</el-button><el-button type="primary" @click="handleSubmit">{{ formMode === 'create' ? '创建' : '保存' }}</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.kb-view { max-width: 1024px; margin: 0 auto; }
.kb-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.kb-card { cursor: pointer; margin-bottom: 16px; min-height: 120px; }
.kb-card:hover { border-color: #409EFF; }
.kb-card-header { display: flex; justify-content: space-between; align-items: center; }
.kb-card-actions { display: flex; align-items: center; gap: 4px; }
.kb-card-name { font-size: 16px; font-weight: 600; }
.kb-card-tags { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.kb-card-owner { font-size: 12px; color: #909399; }
.kb-card-desc { margin-top: 8px; color: #909399; font-size: 13px; }
.kb-card-meta { margin-top: 12px; font-size: 12px; color: #c0c4cc; }
.kb-detail-header { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; margin-bottom: 16px; }
.kb-back-button { padding: 0; }
.kb-detail-title { margin: 0; font-size: 24px; font-weight: 600; color: #303133; }
.visibility-radio { display: flex; align-items: flex-start; height: auto; margin: 0 0 8px; white-space: normal; }
.visibility-radio:last-child { margin-bottom: 0; }
.visibility-radio :deep(.el-radio__input) { margin-top: 4px; }
.visibility-radio :deep(.el-radio__label) { white-space: normal; line-height: 22px; }
</style>
