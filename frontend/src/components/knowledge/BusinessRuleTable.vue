<script setup lang="ts">
import { computed } from 'vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import BusinessRuleForm from './BusinessRuleForm.vue'
import KnowledgeResourceTable from './KnowledgeResourceTable.vue'
const props = defineProps<{ kbId: string }>()
const store = useKnowledgeStore()
const items = computed(() => store.businessRules)
const columns = [{ prop: 'rule_name', label: '规则名称' }, { prop: 'rule_type', label: '类型', width: 80 }, { prop: 'expression', label: '表达式' }, { prop: 'source', label: '来源', width: 140 }]
</script>
<template><KnowledgeResourceTable :items="items" :columns="columns" :form-component="BusinessRuleForm" add-label="添加规则" dialog-label="规则" :create="d => store.createBusinessRule(props.kbId, d)" :update="(id, d) => store.updateBusinessRule(props.kbId, id, d)" :remove="id => store.deleteBusinessRule(props.kbId, id)"><template #cell-rule_type="{ row }"><el-tag :type="row.rule_type === 'hard' ? 'danger' : 'warning'" size="small">{{ row.rule_type === 'hard' ? '硬规则' : '软规则' }}</el-tag></template></KnowledgeResourceTable></template>
