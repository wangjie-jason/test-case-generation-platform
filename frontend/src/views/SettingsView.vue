<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { llmConfigApi } from '@/api/llmConfig'
import { authApi } from '@/api/auth'
import type { LlmConfigStatus } from '@/types/llmConfig'

const status = ref<LlmConfigStatus | null>(null)
const baseUrl = ref('')
const apiKey = ref('')
const model = ref('')
const saving = ref(false)
const testing = ref(false)

const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const changingPwd = ref(false)

async function load() {
  status.value = await llmConfigApi.get()
  baseUrl.value = status.value.base_url ?? ''
  model.value = status.value.model ?? ''
  apiKey.value = ''
}

function effectiveLabel(): string {
  if (status.value?.configured) return `我的凭据 · ${status.value.model}`
  if (status.value?.fallback_available) return `系统默认 · ${status.value.fallback_model}`
  return '未配置'
}

async function onSave() {
  if (!baseUrl.value.trim() || !model.value.trim()) {
    ElMessage.warning('请填写 base_url 和模型名')
    return
  }
  if (!status.value?.configured && !apiKey.value.trim()) {
    ElMessage.warning('首次配置必须填写 API Key')
    return
  }
  saving.value = true
  try {
    status.value = await llmConfigApi.save({
      base_url: baseUrl.value.trim(),
      model: model.value.trim(),
      api_key: apiKey.value,
    })
    apiKey.value = ''
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    saving.value = false
  }
}

async function onTest() {
  testing.value = true
  try {
    // 表单有改动时按当前表单值测（先测后存），否则测已生效配置。
    const dirty = baseUrl.value.trim() !== (status.value?.base_url ?? '')
      || model.value.trim() !== (status.value?.model ?? '')
      || !!apiKey.value.trim()
    const res = await llmConfigApi.test(
      dirty ? { base_url: baseUrl.value, api_key: apiKey.value, model: model.value } : undefined,
    )
    if (res.ok) ElMessage.success(`${res.message}（${res.latency_ms} ms）`)
    else ElMessage.error(res.message)
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    testing.value = false
  }
}

async function onClear() {
  try {
    await ElMessageBox.confirm('清除后将改用系统默认模型，确定清除我的凭据？', '确认', { type: 'warning' })
    const res = await llmConfigApi.clear()
    ElMessage.success(res.message)
    await load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error((e as Error).message)
  }
}

async function onChangePassword() {
  if (!oldPassword.value || !newPassword.value) {
    ElMessage.warning('请填写原密码和新密码')
    return
  }
  if (newPassword.value.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  changingPwd.value = true
  try {
    await authApi.changePassword(oldPassword.value, newPassword.value)
    ElMessage.success('密码已修改')
    oldPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    changingPwd.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="settings-page">
    <el-card class="settings-card">
      <template #header>
        <div class="card-header">
          <span>大模型凭据</span>
          <el-tag :type="status?.configured ? 'success' : (status?.fallback_available ? 'info' : 'danger')">
            当前生效：{{ effectiveLabel() }}
          </el-tag>
        </div>
      </template>

      <el-alert
        v-if="status && !status.configured && status.fallback_available"
        type="info"
        :closable="false"
        class="mb-16"
        title="你正在使用系统默认模型（由平台统一付费）。填写下方个人凭据后，生成将改用你自己的额度。"
      />
      <el-alert
        v-if="status && !status.configured && !status.fallback_available"
        type="error"
        :closable="false"
        class="mb-16"
        title="平台未配置系统默认模型，你必须填写个人凭据后才能生成用例。"
      />

      <el-form label-width="92px" @submit.prevent>
        <el-form-item label="Base URL">
          <el-input v-model="baseUrl" placeholder="https://api.openai.com/v1" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="apiKey"
            type="password"
            show-password
            :placeholder="status?.configured ? `已保存（${status.api_key_masked}），留空表示不修改` : 'sk-...'"
          />
        </el-form-item>
        <el-form-item label="模型名">
          <el-input v-model="model" placeholder="gpt-4o-mini / glm-4-flash / deepseek-chat" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
          <el-button :loading="testing" @click="onTest">连通测试</el-button>
          <el-button v-if="status?.configured" type="danger" plain @click="onClear">
            清除，改用系统默认
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="settings-card">
      <template #header><span>修改密码</span></template>
      <el-form label-width="92px" @submit.prevent>
        <el-form-item label="原密码">
          <el-input v-model="oldPassword" type="password" show-password autocomplete="off" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="newPassword" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="confirmPassword" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="changingPwd" @click="onChangePassword">修改密码</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.settings-page {
  padding: 20px;
  max-width: 720px;
}
.settings-card {
  margin-bottom: 20px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
}
.mb-16 {
  margin-bottom: 16px;
}
</style>
