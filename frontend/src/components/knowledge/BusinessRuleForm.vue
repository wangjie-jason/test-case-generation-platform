<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{ initial: any }>()
const emit = defineEmits(['submit', 'cancel'])

const defaultForm = {
  rule_name: '',
  rule_type: 'hard',
  expression: '',
  description: '',
  source: '',
}

const defaultExpressionParts = {
  left: '',
  operator: '->',
  right: '',
}

const form = ref({ ...defaultForm })

const expressionParts = ref({ ...defaultExpressionParts })

const operatorOptions = [
  { label: '大于 (>)', value: '>' },
  { label: '小于 (<)', value: '<' },
  { label: '大于等于 (>=)', value: '>=' },
  { label: '小于等于 (<=)', value: '<=' },
  { label: '等于 (=)', value: '=' },
  { label: '不等于 (!=)', value: '!=' },
  { label: '则 / 推导 (->)', value: '->' },
]

function parseExpression(expression: string) {
  expressionParts.value = { ...defaultExpressionParts }

  const operators = ['->', '>=', '<=', '!=', '>', '<', '=']
  const matched = operators.find((operator) => expression.includes(operator))

  if (!matched) {
    expressionParts.value.left = expression
    return
  }

  const [left, ...rightParts] = expression.split(matched)
  expressionParts.value.left = left.trim()
  expressionParts.value.operator = matched
  expressionParts.value.right = rightParts.join(matched).trim()
}

function syncExpression() {
  const left = expressionParts.value.left.trim()
  const right = expressionParts.value.right.trim()
  form.value.expression = `${left}${expressionParts.value.operator}${right}`
}

watch(
  () => props.initial,
  (initial) => {
    form.value = { ...defaultForm, ...(initial || {}) }
    parseExpression(form.value.expression)
  },
  { immediate: true },
)

function onSubmit() {
  syncExpression()
  emit('submit', { ...form.value })
}
</script>

<template>
  <el-form @submit.prevent="onSubmit" label-width="100px">
    <el-form-item label="规则名称" required>
      <el-input v-model="form.rule_name" placeholder="如 VIP免运费" />
    </el-form-item>
    <el-form-item label="类型" required>
      <el-select v-model="form.rule_type">
        <el-option label="硬规则 (代码强制)" value="hard" />
        <el-option label="软规则 (业务惯例)" value="soft" />
      </el-select>
    </el-form-item>
    <el-form-item label="表达式" required>
      <div class="expression-builder">
        <el-input v-model="expressionParts.left" placeholder="如 vip" />
        <el-select v-model="expressionParts.operator" placeholder="关系" class="operator-select">
          <el-option
            v-for="option in operatorOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-input v-model="expressionParts.right" placeholder="如免运费" />
      </div>
    </el-form-item>
    <el-form-item label="描述">
      <el-input v-model="form.description" type="textarea" />
    </el-form-item>
    <el-form-item label="来源">
      <el-input v-model="form.source" placeholder="如 PRD v3.2 + 代码逻辑" />
    </el-form-item>
    <el-form-item>
      <el-button @click="emit('cancel')">取消</el-button>
      <el-button type="primary" @click="onSubmit">确定</el-button>
    </el-form-item>
  </el-form>
</template>

<style scoped>
.expression-builder {
  display: flex;
  gap: 8px;
  width: 100%;
}

.operator-select {
  flex: 0 0 160px;
}

@media (max-width: 640px) {
  .expression-builder {
    flex-direction: column;
  }

  .operator-select {
    flex-basis: auto;
  }
}
</style>
