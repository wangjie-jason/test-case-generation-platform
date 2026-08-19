<script setup lang="ts">
import { computed } from 'vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import StateMachineForm from './StateMachineForm.vue'
import KnowledgeResourceTable from './KnowledgeResourceTable.vue'
const props = defineProps<{ kbId: string }>()
const store = useKnowledgeStore()
const items = computed(() => store.stateMachines)
const columns = [{ prop: 'entity', label: '实体' }, { prop: 'from_state', label: '源状态' }, { prop: 'to_state', label: '目标状态' }, { prop: 'condition', label: '条件' }]
</script>
<template><KnowledgeResourceTable :items="items" :columns="columns" :form-component="StateMachineForm" add-label="添加状态流转" dialog-label="状态流转" :create="d => store.createStateMachine(props.kbId, d)" :update="(id, d) => store.updateStateMachine(props.kbId, id, d)" :remove="id => store.deleteStateMachine(props.kbId, id)" /></template>
