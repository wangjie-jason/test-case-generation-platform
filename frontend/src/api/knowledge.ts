import client from './client'
import type { FieldDict, BusinessRule, StateMachine, TermMapping, PrdDocument, DefectRecord } from '@/types/knowledge'
import type { KnowledgeBase } from '@/types/project'

// 知识库
export const kbApi = {
  list() { return client.get<any, KnowledgeBase[]>("/knowledge-bases") },
  create(data: { name: string; description?: string }) { return client.post<any, KnowledgeBase>('/knowledge-bases', data) },
  delete(id: string) { return client.delete(`/knowledge-bases/${id}`) },
}

// 结构化知识，按知识库 ID 隔离。
export const fieldDictApi = {
  list(kbId: string) { return client.get<any, FieldDict[]>(`/knowledge-bases/${kbId}/field-dicts`) },
  create(kbId: string, d: Partial<FieldDict>) { return client.post<any, FieldDict>(`/knowledge-bases/${kbId}/field-dicts`, d) },
  update(kbId: string, id: string, d: Partial<FieldDict>) { return client.put<any, FieldDict>(`/knowledge-bases/${kbId}/field-dicts/${id}`, d) },
  delete(kbId: string, id: string) { return client.delete(`/knowledge-bases/${kbId}/field-dicts/${id}`) },
}

export const businessRuleApi = {
  list(kbId: string) { return client.get<any, BusinessRule[]>(`/knowledge-bases/${kbId}/business-rules`) },
  create(kbId: string, d: Partial<BusinessRule>) { return client.post<any, BusinessRule>(`/knowledge-bases/${kbId}/business-rules`, d) },
  update(kbId: string, id: string, d: Partial<BusinessRule>) { return client.put<any, BusinessRule>(`/knowledge-bases/${kbId}/business-rules/${id}`, d) },
  delete(kbId: string, id: string) { return client.delete(`/knowledge-bases/${kbId}/business-rules/${id}`) },
}

export const stateMachineApi = {
  list(kbId: string) { return client.get<any, StateMachine[]>(`/knowledge-bases/${kbId}/state-machines`) },
  create(kbId: string, d: Partial<StateMachine>) { return client.post<any, StateMachine>(`/knowledge-bases/${kbId}/state-machines`, d) },
  update(kbId: string, id: string, d: Partial<StateMachine>) { return client.put<any, StateMachine>(`/knowledge-bases/${kbId}/state-machines/${id}`, d) },
  delete(kbId: string, id: string) { return client.delete(`/knowledge-bases/${kbId}/state-machines/${id}`) },
}

export const termMappingApi = {
  list(kbId: string) { return client.get<any, TermMapping[]>(`/knowledge-bases/${kbId}/term-mappings`) },
  create(kbId: string, d: Partial<TermMapping>) { return client.post<any, TermMapping>(`/knowledge-bases/${kbId}/term-mappings`, d) },
  update(kbId: string, id: string, d: Partial<TermMapping>) { return client.put<any, TermMapping>(`/knowledge-bases/${kbId}/term-mappings/${id}`, d) },
  delete(kbId: string, id: string) { return client.delete(`/knowledge-bases/${kbId}/term-mappings/${id}`) },
}

// PRD 文档
export const prdDocumentApi = {
  list(kbId: string) { return client.get<any, PrdDocument[]>(`/knowledge-bases/${kbId}/prd-documents`) },
  upload(kbId: string, file: File, onProgress?: (pct: number) => void) {
    const form = new FormData(); form.append('file', file)
    return client.post<any, PrdDocument>(`/knowledge-bases/${kbId}/prd-documents/upload`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e: any) => { if (e.total && onProgress) onProgress(Math.round((e.loaded * 100) / e.total)) },
    })
  },
  delete(kbId: string, id: string) { return client.delete(`/knowledge-bases/${kbId}/prd-documents/${id}`) },
}

// 缺陷记录
export const defectRecordApi = {
  list(kbId: string) { return client.get<any, DefectRecord[]>(`/knowledge-bases/${kbId}/defect-records`) },
  create(kbId: string, d: Partial<DefectRecord>) { return client.post<any, DefectRecord>(`/knowledge-bases/${kbId}/defect-records`, d) },
  update(kbId: string, id: string, d: Partial<DefectRecord>) { return client.put<any, DefectRecord>(`/knowledge-bases/${kbId}/defect-records/${id}`, d) },
  delete(kbId: string, id: string) { return client.delete(`/knowledge-bases/${kbId}/defect-records/${id}`) },
  importExcel(kbId: string, file: File) {
    const form = new FormData(); form.append('file', file)
    return client.post<any, { imported: number }>(`/knowledge-bases/${kbId}/import-defects`, form, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
}
