<template>
  <div>
    <n-space vertical :size="20">
      <n-card :title="t('users.title')">
        <template #header-extra>
          <n-button size="small" @click="load" :loading="loading">{{ t('users.btnRefresh') }}</n-button>
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
import { ref, computed, h, onMounted } from 'vue'
import { NTag, NButton, NSpace, NInputNumber, NSelect, NPopconfirm, NSwitch, NText } from 'naive-ui'
import { listUsers, updateUser, deleteUser, getGpuStatus } from '../../api/adminApi'
import { useAuthStore } from '../../stores/auth'
import { useI18n } from '../../i18n/index.js'

const { t } = useI18n()
const auth = useAuthStore()
const users = ref([])
const loading = ref(false)
const maxQuota = ref(16)

const roleOptions = computed(() => [
  { label: t('users.role.user'), value: 'user' },
  { label: t('users.role.admin'), value: 'admin' },
])

const columns = computed(() => [
  { title: t('users.col.username'), key: 'username', width: 140 },
  { title: t('users.col.email'), key: 'email', render: (r) => r.email || '—' },
  {
    title: t('users.col.role'),
    key: 'role',
    width: 130,
    render: (r) => h(NSelect, {
      value: r.role,
      options: roleOptions.value,
      size: 'small',
      style: 'width: 110px',
      disabled: r.id === auth.user?.id,
      onUpdateValue: (val) => handlePatch(r, { role: val }),
    }),
  },
  {
    title: t('users.col.quota'),
    key: 'gpu_quota',
    width: 160,
    render: (r) => {
      const parts = [
        h(NInputNumber, {
          value: r.gpu_quota,
          min: 0,
          max: maxQuota.value,
          size: 'small',
          style: 'width: 90px',
          onUpdateValue: (val) => handlePatch(r, { gpu_quota: val }),
        }),
      ]
      if (r.gpu_quota === 0) {
        parts.push(
          h(NText, { depth: 3, style: 'font-size: 12px; margin-left: 4px' },
            { default: () => t('users.quota.unlimited') })
        )
      }
      return h(NSpace, { align: 'center', size: 4, wrap: false }, { default: () => parts })
    },
  },
  {
    title: t('users.col.active'),
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
    title: t('users.col.actions'),
    key: 'actions',
    width: 100,
    render: (r) => h(NPopconfirm, {
      onPositiveClick: () => handleDelete(r),
    }, {
      trigger: () => h(NButton, {
        size: 'small', type: 'error', secondary: true, disabled: r.id === auth.user?.id,
      }, { default: () => t('users.btn.delete') }),
      default: () => t('users.confirm.delete', { name: r.username }),
    }),
  },
])

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
    window.$message?.success(t('users.msg.updated'))
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Update failed')
    await load()
  }
}

async function handleDelete(user) {
  try {
    await deleteUser(user.id)
    await load()
    window.$message?.success(t('users.msg.deleted'))
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Delete failed')
  }
}

onMounted(async () => {
  await load()
  try {
    const status = await getGpuStatus()
    maxQuota.value = status.pool?.total_slots || 16
  } catch {}
})
</script>
