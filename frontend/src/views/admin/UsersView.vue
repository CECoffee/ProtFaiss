<template>
  <div>
    <n-space vertical :size="20">
      <n-card title="User Management">
        <template #header-extra>
          <n-button size="small" @click="load" :loading="loading">Refresh</n-button>
        </template>
        <n-data-table
          :columns="columns"
          :data="users"
          :pagination="{ pageSize: 20 }"
          size="small"
          striped
        />
      </n-card>
    </n-space>
  </div>
</template>

<script setup>
import { ref, h, onMounted } from 'vue'
import { NTag, NButton, NSpace, NInputNumber, NSelect, NPopconfirm, NSwitch } from 'naive-ui'
import { listUsers, updateUser, deleteUser } from '../../api/adminApi'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()
const users = ref([])
const loading = ref(false)

const roleOptions = [
  { label: 'User', value: 'user' },
  { label: 'Admin', value: 'admin' },
]

const columns = [
  { title: 'Username', key: 'username', width: 140 },
  { title: 'Email', key: 'email', render: (r) => r.email || '—' },
  {
    title: 'Role',
    key: 'role',
    width: 130,
    render: (r) => h(NSelect, {
      value: r.role,
      options: roleOptions,
      size: 'small',
      style: 'width: 110px',
      disabled: r.id === auth.user?.id,
      onUpdateValue: (val) => handlePatch(r, { role: val }),
    }),
  },
  {
    title: 'GPU Quota',
    key: 'gpu_quota',
    width: 120,
    render: (r) => h(NInputNumber, {
      value: r.gpu_quota,
      min: 0,
      max: 16,
      size: 'small',
      style: 'width: 90px',
      onUpdateValue: (val) => handlePatch(r, { gpu_quota: val }),
    }),
  },
  {
    title: 'Active',
    key: 'is_active',
    width: 90,
    render: (r) => h(NSwitch, {
      value: r.is_active,
      size: 'small',
      disabled: r.id === auth.user?.id,
      onUpdateValue: (val) => handlePatch(r, { is_active: val }),
    }),
  },
  {
    title: 'Actions',
    key: 'actions',
    width: 100,
    render: (r) => h(NPopconfirm, {
      onPositiveClick: () => handleDelete(r),
    }, {
      trigger: () => h(NButton, {
        size: 'small',
        type: 'error',
        secondary: true,
        disabled: r.id === auth.user?.id,
      }, { default: () => 'Delete' }),
      default: () => `Delete user "${r.username}"?`,
    }),
  },
]

async function load() {
  loading.value = true
  try {
    const data = await listUsers()
    users.value = data.users || []
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Load failed')
  }
  loading.value = false
}

async function handlePatch(user, patch) {
  try {
    const updated = await updateUser(user.id, patch)
    Object.assign(user, updated)
    window.$message?.success('Updated')
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Update failed')
    await load()
  }
}

async function handleDelete(user) {
  try {
    await deleteUser(user.id)
    await load()
    window.$message?.success('User deleted')
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Delete failed')
  }
}

onMounted(load)
</script>
