<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi, type AdminCreateUser } from '@/api/admin'
import { useAuthStore } from '@/stores/auth'
import type { AuthUser } from '@/types/auth'

const auth = useAuthStore()
const users = ref<AuthUser[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)
const form = ref<AdminCreateUser>({ username: '', password: '', display_name: '', is_admin: false })

async function load() {
  loading.value = true
  try {
    users.value = await adminApi.listUsers()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = { username: '', password: '', display_name: '', is_admin: false }
  dialogVisible.value = true
}

async function createUser() {
  if (!form.value.username.trim() || !form.value.password) {
    ElMessage.warning('用户名和密码必填')
    return
  }
  if (form.value.password.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  saving.value = true
  try {
    await adminApi.createUser({
      ...form.value,
      username: form.value.username.trim(),
      display_name: form.value.display_name?.trim() || undefined,
    })
    ElMessage.success('已创建')
    dialogVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    saving.value = false
  }
}

async function toggleActive(u: AuthUser) {
  const next = !u.is_active
  try {
    await ElMessageBox.confirm(next ? `确定启用「${u.username}」？` : `确定停用「${u.username}」？停用后其登录立即失效`, '确认', { type: 'warning' })
    await adminApi.updateUser(u.id, { is_active: next })
    ElMessage.success('已更新')
    await load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error((e as Error).message)
    await load() // 后端可能拒绝（操作自己/末位管理员），回滚开关状态
  }
}

async function toggleAdmin(u: AuthUser) {
  try {
    await adminApi.updateUser(u.id, { is_admin: !u.is_admin })
    ElMessage.success('已更新')
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
    await load()
  }
}

async function resetPassword(u: AuthUser) {
  try {
    const { value } = await ElMessageBox.prompt(`为「${u.username}」设置新密码（至少 6 位）`, '重置密码', {
      confirmButtonText: '重置', cancelButtonText: '取消', inputType: 'password',
      inputValidator: (v: string) => (v && v.length >= 6) || '至少 6 位',
    })
    await adminApi.resetPassword(u.id, value)
    ElMessage.success('密码已重置')
  } catch (e) {
    if (e !== 'cancel' && e !== undefined) ElMessage.error((e as Error).message)
  }
}

onMounted(load)
</script>

<template>
  <div class="users-view">
    <div class="users-header">
      <h2>用户管理</h2>
      <el-button type="primary" @click="openCreate">+ 新建用户</el-button>
    </div>

    <el-table :data="users" border stripe v-loading="loading">
      <el-table-column prop="username" label="用户名" width="160" />
      <el-table-column label="姓名" width="160">
        <template #default="{ row }">{{ row.display_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="角色" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.is_admin" type="warning" size="small">管理员</el-tag>
          <el-tag v-else type="info" size="small">成员</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180">
        <template #default="{ row }">{{ row.created_at?.slice(0, 19).replace('T', ' ') }}</template>
      </el-table-column>
      <el-table-column label="操作" min-width="240">
        <template #default="{ row }">
          <el-button link type="primary" @click="resetPassword(row)">重置密码</el-button>
          <el-button
            link :type="row.is_admin ? 'warning' : 'primary'"
            :disabled="row.id === auth.user?.id"
            @click="toggleAdmin(row)"
          >{{ row.is_admin ? '取消管理员' : '设为管理员' }}</el-button>
          <el-button
            link :type="row.is_active ? 'danger' : 'success'"
            :disabled="row.id === auth.user?.id"
            @click="toggleActive(row)"
          >{{ row.is_active ? '停用' : '启用' }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" title="新建用户" width="440px">
      <el-form label-width="84px" @submit.prevent>
        <el-form-item label="用户名" required><el-input v-model="form.username" autocomplete="off" /></el-form-item>
        <el-form-item label="显示名"><el-input v-model="form.display_name" placeholder="选填" /></el-form-item>
        <el-form-item label="初始密码" required><el-input v-model="form.password" type="password" show-password /></el-form-item>
        <el-form-item label="管理员"><el-switch v-model="form.is_admin" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createUser">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.users-view { max-width: 1024px; margin: 0 auto; }
.users-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
</style>
