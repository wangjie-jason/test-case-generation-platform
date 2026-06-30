<script setup lang="ts">
import { ref, onMounted } from 'vue'

const props = defineProps<{ initial: any }>()
const emit = defineEmits(['submit', 'cancel'])

const form = ref({
  ui_term: '',
  tech_field: '',
  mapping_desc: '',
})

onMounted(() => {
  if (props.initial) Object.assign(form.value, props.initial)
})

function onSubmit() { emit('submit', { ...form.value }) }
</script>

<template>
  <el-form @submit.prevent="onSubmit" label-width="100px">
    <el-form-item label="页面术语" required>
      <el-input v-model="form.ui_term" placeholder="如 设备数 (页面上的名称)" />
    </el-form-item>
    <el-form-item label="技术字段" required>
      <el-input v-model="form.tech_field" placeholder="如 channel_count (实际字段名)" />
    </el-form-item>
    <el-form-item label="映射说明">
      <el-input v-model="form.mapping_desc" type="textarea" placeholder="如 1个摄像机包含多个通道，页面写设备数实际对应通道数" />
    </el-form-item>
    <el-form-item>
      <el-button @click="emit('cancel')">取消</el-button>
      <el-button type="primary" @click="onSubmit">确定</el-button>
    </el-form-item>
  </el-form>
</template>
