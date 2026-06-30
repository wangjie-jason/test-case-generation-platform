import client from './client'
import type { GeneratedTestCase } from '@/types/testCase'

export const exportApi = {
  downloadCases(cases: GeneratedTestCase[]) {
    return client.post<any, Blob>('/cases/export', { cases }, { responseType: 'blob' })
  },
}
