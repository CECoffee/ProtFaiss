<template>
  <div>
    <n-space vertical :size="20">
      <!-- Stats -->
      <n-card title="System Statistics">
        <template #header-extra>
          <n-button size="small" @click="loadStats" :loading="statsLoading">Refresh</n-button>
        </template>
        <n-grid :cols="4" :x-gap="16" v-if="stats">
          <n-gi><n-statistic label="Users" :value="stats.user_count" /></n-gi>
          <n-gi><n-statistic label="Datasets" :value="stats.dataset_count" /></n-gi>
          <n-gi><n-statistic label="Running Tasks" :value="stats.running_gpu_tasks" /></n-gi>
          <n-gi><n-statistic label="Pending Tasks" :value="stats.pending_gpu_tasks" /></n-gi>
        </n-grid>
      </n-card>

      <!-- GPU Queue (admin view) -->
      <n-card title="Full GPU Queue">
        <template #header-extra>
          <n-button size="small" @click="loadQueue" :loading="queueLoading">Refresh</n-button>
        </template>
        <n-data-table
          :columns="queueColumns"
          :data="queue"
          :pagination="{ pageSize: 20 }"
          size="small"
          striped
        />
        <n-empty v-if="!queue.length && !queueLoading" description="No active GPU tasks" />
      </n-card>

      <!-- Config reload -->
      <n-card title="Configuration">
        <n-space>
          <n-button type="warning" @click="handleReloadConfig" :loading="reloading">
            Reload config.yml
          </n-button>
          <n-text depth="3" style="font-size: 0.85rem">
            Reloads GPU slots, scheduler settings, and other hot-reloadable config.
          </n-text>
        </n-space>
      </n-card>
    </n-space>
  </div>
</template>

<script setup>
import { ref, h, onMounted } from 'vue'
import { NTag, NButton, NPopconfirm } from 'naive-ui'
import { getStats, getGpuQueue, cancelTask, reloadConfig } from '../../api/adminApi'

const stats = ref(null)
const statsLoading = ref(false)
const queue = ref([])
const queueLoading = ref(false)
const reloading = ref(false)

const statusTypeMap = { pending: 'warning', running: 'info', done: 'success', failed: 'error', cancelled: 'default' }

const queueColumns = [
  { title: 'User', key: 'username', width: 120 },
  { title: 'Type', key: 'task_type', width: 80,
    render: (r) => h(NTag, { size: 'small', type: r.task_type === 'search' ? 'info' : 'warning', round: true }, { default: () => r.task_type }) },
  { title: 'Status', key: 'status', width: 100,
    render: (r) => h(NTag, { size: 'small', type: statusTypeMap[r.status] || 'default', round: true }, { default: () => r.status }) },
  { title: 'Priority', key: 'priority', width: 80 },
  { title: 'GPU Slots', key: 'gpu_slots', width: 90 },
  { title: 'Submitted', key: 'submitted_at', render: (r) => r.submitted_at ? new Date(r.submitted_at).toLocaleTimeString() : '—' },
  {
    title: 'Actions',
    key: 'actions',
    width: 100,
    render: (r) => r.status === 'pending' ? h(NPopconfirm, {
      onPositiveClick: () => handleCancel(r.id),
    }, {
      trigger: () => h(NButton, { size: 'small', type: 'error', secondary: true }, { default: () => 'Cancel' }),
      default: () => 'Cancel this task?',
    }) : null,
  },
]

async function loadStats() {
  statsLoading.value = true
  try {
    stats.value = await getStats()
  } catch {}
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
    window.$message?.success('Task cancelled')
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Cancel failed')
  }
}

async function handleReloadConfig() {
  reloading.value = true
  try {
    await reloadConfig()
    window.$message?.success('Config reloaded')
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
