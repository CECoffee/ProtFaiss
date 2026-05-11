<template>
  <div>
    <n-space vertical :size="20">
      <!-- Stats -->
      <n-card :title="t('system.stats')">
        <template #header-extra>
          <n-button size="small" @click="loadStats" :loading="statsLoading">{{ t('system.btnRefresh') }}</n-button>
        </template>
        <n-grid :cols="4" :x-gap="16" v-if="stats">
          <n-gi><n-statistic :label="t('system.stat.users')" :value="stats.user_count" /></n-gi>
          <n-gi><n-statistic :label="t('system.stat.datasets')" :value="stats.dataset_count" /></n-gi>
          <n-gi><n-statistic :label="t('system.stat.running')" :value="stats.running_gpu_tasks" /></n-gi>
          <n-gi><n-statistic :label="t('system.stat.pending')" :value="stats.pending_gpu_tasks" /></n-gi>
        </n-grid>
      </n-card>

      <!-- GPU Queue (admin view) -->
      <n-card :title="t('system.queue')">
        <template #header-extra>
          <n-button size="small" @click="loadQueue" :loading="queueLoading">{{ t('system.btnRefresh') }}</n-button>
        </template>
        <n-data-table
          :columns="queueColumns"
          :data="queue"
          :pagination="{ pageSize: 20 }"
          size="small"
          striped
        />
      </n-card>

      <!-- Config reload -->
      <n-card :title="t('system.config')">
        <n-space>
          <n-button type="warning" @click="handleReloadConfig" :loading="reloading">
            {{ t('system.btnReload') }}
          </n-button>
          <n-text depth="3" style="font-size: 0.85rem">{{ t('system.reloadHint') }}</n-text>
        </n-space>
      </n-card>
    </n-space>
  </div>
</template>

<script setup>
import { ref, computed, h, onMounted } from 'vue'
import { NTag, NButton, NPopconfirm } from 'naive-ui'
import { getStats, getGpuQueue, cancelTask, reloadConfig } from '../../api/adminApi'
import { useI18n } from '../../i18n/index.js'

const { t } = useI18n()

const stats = ref(null)
const statsLoading = ref(false)
const queue = ref([])
const queueLoading = ref(false)
const reloading = ref(false)

const statusTypeMap = { pending: 'warning', running: 'info', done: 'success', failed: 'error', cancelled: 'default' }

const queueColumns = computed(() => [
  { title: t('system.col.user'), key: 'username', width: 120 },
  { title: t('system.col.type'), key: 'task_type', width: 80,
    render: (r) => h(NTag, { size: 'small', type: r.task_type === 'search' ? 'info' : 'warning', round: true }, { default: () => r.task_type }) },
  { title: t('system.col.status'), key: 'status', width: 100,
    render: (r) => h(NTag, { size: 'small', type: statusTypeMap[r.status] || 'default', round: true }, { default: () => r.status }) },
  { title: t('system.col.priority'), key: 'priority', width: 80 },
  { title: t('system.col.slots'), key: 'gpu_slots', width: 90 },
  { title: t('system.col.submitted'), key: 'submitted_at', render: (r) => r.submitted_at ? new Date(r.submitted_at).toLocaleTimeString() : '—' },
  {
    title: t('system.col.actions'),
    key: 'actions',
    width: 100,
    render: (r) => r.status === 'pending' || r.status === 'running' ? h(NPopconfirm, {
      onPositiveClick: () => handleCancel(r.id),
    }, {
      trigger: () => h(NButton, { size: 'small', type: 'error', secondary: true }, { default: () => t('system.btn.cancel') }),
      default: () => t('system.confirm.cancel'),
    }) : null,
  },
])

async function loadStats() {
  statsLoading.value = true
  try { stats.value = await getStats() } catch {}
  statsLoading.value = false
}

async function loadQueue() {
  queueLoading.value = true
  try {
    const data = await getGpuQueue()
    queue.value = data.tasks || []
  } catch {}
  queueLoading.value = false
}

async function handleCancel(id) {
  try {
    await cancelTask(id)
    await loadQueue()
    window.$message?.success(t('system.msg.cancelled'))
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Cancel failed')
  }
}

async function handleReloadConfig() {
  reloading.value = true
  try {
    await reloadConfig()
    window.$message?.success(t('system.msg.reloaded'))
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Reload failed')
  }
  reloading.value = false
}

onMounted(() => {
  loadStats()
  loadQueue()
})
</script>
