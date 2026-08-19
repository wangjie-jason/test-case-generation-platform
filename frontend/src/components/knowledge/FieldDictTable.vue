<script setup lang="ts">
import { computed } from 'vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import FieldDictForm from './FieldDictForm.vue'
import KnowledgeResourceTable from './KnowledgeResourceTable.vue'

const props = defineProps<{ kbId: string }>()
const store = useKnowledgeStore()
const items = computed(() => store.fieldDicts)

const columns = [
  { prop: 'field_name', label: '字段名' },
  { prop: 'display_name', label: '页面展示名' },
  { prop: 'data_type', label: '类型', width: 80 },
  { prop: 'enum_values', label: '枚举值' },
  { prop: 'description', label: '业务含义' },
]
</script>

<template>
  <KnowledgeResourceTable
    :items="items" :columns="columns" :form-component="FieldDictForm"
    add-label="添加字段" dialog-label="字段"
    :create="d => store.createFieldDict(props.kbId, d)"
    :update="(id, d) => store.updateFieldDict(props.kbId, id, d)"
    :remove="id => store.deleteFieldDict(props.kbId, id)"
  />
</template>
