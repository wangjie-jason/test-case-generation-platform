import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fieldDictApi, businessRuleApi, stateMachineApi, termMappingApi, prdDocumentApi, defectRecordApi, kbApi } from '@/api/knowledge'
import type { FieldDict, BusinessRule, StateMachine, TermMapping, PrdDocument, DefectRecord } from '@/types/knowledge'
import type { KnowledgeBase } from '@/types/project'

export const useKnowledgeStore = defineStore('knowledge', () => {
  const kbs = ref<KnowledgeBase[]>([])
  const currentKb = ref<KnowledgeBase | null>(null)
  const fieldDicts = ref<FieldDict[]>([]); const businessRules = ref<BusinessRule[]>([])
  const stateMachines = ref<StateMachine[]>([]); const termMappings = ref<TermMapping[]>([])
  const prdDocuments = ref<PrdDocument[]>([]); const defectRecords = ref<DefectRecord[]>([])
  const loadingDetails = ref(false)

  async function fetchKbs() { kbs.value = await kbApi.list() }
  async function createKb(data: { name: string; description?: string }) { const kb = await kbApi.create(data); kbs.value.push(kb); return kb }
  async function deleteKb(id: string) { await kbApi.delete(id); kbs.value = kbs.value.filter(k => k.id !== id) }
  function selectKb(kb: KnowledgeBase | null) { currentKb.value = kb }

  function clearDetails() {
    fieldDicts.value = []; businessRules.value = []
    stateMachines.value = []; termMappings.value = []
    prdDocuments.value = []; defectRecords.value = []
  }

  async function _fetch(kbId: string) {
    if (!kbId) return
    loadingDetails.value = true
    clearDetails()
    try {
      fieldDicts.value = await fieldDictApi.list(kbId); businessRules.value = await businessRuleApi.list(kbId)
      stateMachines.value = await stateMachineApi.list(kbId); termMappings.value = await termMappingApi.list(kbId)
      prdDocuments.value = await prdDocumentApi.list(kbId); defectRecords.value = await defectRecordApi.list(kbId)
    } finally {
      loadingDetails.value = false
    }
  }

  return {
    kbs, currentKb, fieldDicts, businessRules, stateMachines, termMappings, prdDocuments, defectRecords, loadingDetails,
    fetchKbs, createKb, deleteKb, selectKb, clearDetails, _fetch,
    createFieldDict: (kbId: string, d: Partial<FieldDict>) => fieldDictApi.create(kbId, d).then(() => _fetch(kbId)),
    updateFieldDict: (kbId: string, id: string, d: Partial<FieldDict>) => fieldDictApi.update(kbId, id, d).then(() => _fetch(kbId)),
    deleteFieldDict: (kbId: string, id: string) => fieldDictApi.delete(kbId, id).then(() => _fetch(kbId)),
    createBusinessRule: (kbId: string, d: Partial<BusinessRule>) => businessRuleApi.create(kbId, d).then(() => _fetch(kbId)),
    updateBusinessRule: (kbId: string, id: string, d: Partial<BusinessRule>) => businessRuleApi.update(kbId, id, d).then(() => _fetch(kbId)),
    deleteBusinessRule: (kbId: string, id: string) => businessRuleApi.delete(kbId, id).then(() => _fetch(kbId)),
    createStateMachine: (kbId: string, d: Partial<StateMachine>) => stateMachineApi.create(kbId, d).then(() => _fetch(kbId)),
    updateStateMachine: (kbId: string, id: string, d: Partial<StateMachine>) => stateMachineApi.update(kbId, id, d).then(() => _fetch(kbId)),
    deleteStateMachine: (kbId: string, id: string) => stateMachineApi.delete(kbId, id).then(() => _fetch(kbId)),
    createTermMapping: (kbId: string, d: Partial<TermMapping>) => termMappingApi.create(kbId, d).then(() => _fetch(kbId)),
    updateTermMapping: (kbId: string, id: string, d: Partial<TermMapping>) => termMappingApi.update(kbId, id, d).then(() => _fetch(kbId)),
    deleteTermMapping: (kbId: string, id: string) => termMappingApi.delete(kbId, id).then(() => _fetch(kbId)),
    uploadPrd: (kbId: string, file: File, onProgress?: (pct: number) => void) => prdDocumentApi.upload(kbId, file, onProgress).then(() => _fetch(kbId)),
    deletePrd: (kbId: string, id: string) => prdDocumentApi.delete(kbId, id).then(() => { prdDocuments.value = prdDocuments.value.filter(d => d.id !== id) }),
    createDefect: (kbId: string, d: Partial<DefectRecord>) => defectRecordApi.create(kbId, d).then(() => _fetch(kbId)),
    updateDefect: (kbId: string, id: string, d: Partial<DefectRecord>) => defectRecordApi.update(kbId, id, d).then(() => _fetch(kbId)),
    deleteDefect: (kbId: string, id: string) => defectRecordApi.delete(kbId, id).then(() => { defectRecords.value = defectRecords.value.filter(d => d.id !== id) }),
  }
})
