<script setup lang="ts">
import { ref, onMounted } from 'vue'

const props = defineProps<{ initial: any }>()
const emit = defineEmits(['submit', 'cancel'])

const form = ref({
  entity: '',
  from_state: '',
  to_state: '',
  condition: '',
})

onMounted(() => {
  if (props.initial) Object.assign(form.value, props.initial)
})

function onSubmit() { emit('submit', { ...form.value }) }
</script>

<template>
  <el-form @submit.prevent="onSubmit" label-width="80px">
    <el-form-item label="实体" required>
      <el-input v-model="form.entity" placeholder="如 订单" />
    </el-form-item>
    <el-form-item label="源状态" required>
      <el-input v-model="form.from_state" placeholder="如 待支付" />
    </el-form-item>
    <el-form-item label="目标状态" required>
      <el-input v-model="form.to_state" placeholder="如 已支付" />
    </el-form-item>
    <el-form-item label="条件">
      <el-input v-model="form.condition" placeholder="流转条件（可选）" />
    </el-form-item>
    <el-form-item>
      <el-button @click="emit('cancel')">取消</el-button>
      <el-button type="primary" @click="onSubmit">确定</el-button>
    </el-form-item>
  </el-form>
</template>
