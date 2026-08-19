<script setup lang="ts">
import { computed } from 'vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import TermMappingForm from './TermMappingForm.vue'
import KnowledgeResourceTable from './KnowledgeResourceTable.vue'
const props = defineProps<{ kbId: string }>()
const store = useKnowledgeStore()
const items = computed(() => store.termMappings)
const columns = [{ prop: 'ui_term', label: '页面术语' }, { prop: 'tech_field', label: '技术字段' }, { prop: 'mapping_desc', label: '映射说明' }]
</script>
<template><KnowledgeResourceTable :items="items" :columns="columns" :form-component="TermMappingForm" add-label="添加映射" dialog-label="映射" :create="d => store.createTermMapping(props.kbId, d)" :update="(id, d) => store.updateTermMapping(props.kbId, id, d)" :remove="id => store.deleteTermMapping(props.kbId, id)" /></template>
