<script setup lang="ts">
defineProps<{ visible: boolean; title: string; message: string }>()
const emit = defineEmits(['confirm', 'cancel'])
</script>

<template>
  <el-dialog :model-value="visible" :title="title" width="400px" @close="emit('cancel')">
    <p>{{ message }}</p>
    <template #footer>
      <el-button @click="emit('cancel')">取消</el-button>
      <el-button type="primary" @click="emit('confirm')">确定</el-button>
    </template>
  </el-dialog>
</template>
