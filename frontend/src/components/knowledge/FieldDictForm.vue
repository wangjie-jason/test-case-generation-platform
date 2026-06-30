<script setup lang="ts">
import { ref, onMounted } from 'vue'

const props = defineProps<{ initial: any }>()
const emit = defineEmits(['submit', 'cancel'])

const form = ref({
  field_name: '',
  display_name: '',
  data_source: '',
  data_type: 'str',
  enum_values: '',
  description: '',
})

onMounted(() => {
  if (props.initial) {
    Object.assign(form.value, props.initial)
  }
})

function onSubmit() { emit('submit', { ...form.value }) }
</script>

<template>
  <el-form @submit.prevent="onSubmit" label-width="100px">
    <el-form-item label="字段名" required>
      <el-input v-model="form.field_name" placeholder="如 channel_count" />
    </el-form-item>
    <el-form-item label="页面展示名" required>
      <el-input v-model="form.display_name" placeholder="如 设备数" />
    </el-form-item>
    <el-form-item label="数据来源">
      <el-input v-model="form.data_source" placeholder="如 camera表" />
    </el-form-item>
    <el-form-item label="类型" required>
      <el-select v-model="form.data_type">
        <el-option label="字符串 (str)" value="str" />
        <el-option label="整数 (int)" value="int" />
        <el-option label="布尔 (bool)" value="bool" />
        <el-option label="日期 (date)" value="date" />
        <el-option label="枚举 (enum)" value="enum" />
      </el-select>
    </el-form-item>
    <el-form-item label="枚举值">
      <el-input v-model="form.enum_values" placeholder="逗号分隔，如 待支付,已支付,已取消" />
    </el-form-item>
    <el-form-item label="业务含义">
      <el-input v-model="form.description" type="textarea" placeholder="描述该字段的业务含义" />
    </el-form-item>
    <el-form-item>
      <el-button @click="emit('cancel')">取消</el-button>
      <el-button type="primary" @click="onSubmit">确定</el-button>
    </el-form-item>
  </el-form>
</template>
