<template>
  <div>
    <n-space vertical :size="20">
      <!-- GPU Pool overview -->
      <n-grid :cols="3" :x-gap="16">
        <n-gi>
          <n-card size="small">
            <n-statistic label="Total GPU Slots" :value="gpuStore.pool.total_slots" />
          </n-card>
        </n-gi>
        <n-gi>
          <n-card size="small">
            <n-statistic label="Used Slots" :value="gpuStore.pool.used_slots">
              <template #suffix>
                <n-tag :type="usedTagType" size="small" round style="margin-left: 6px">
                  {{ usedPct }}%
                </n-tag>
              </template>
            </n-statistic>
          </n-card>
        </n-gi>
        <n-gi>
          <n-card size="small">
            <n-statistic label="Available Slots" :value="gpuStore.pool.available_slots" />
          </n-card>
        </n-gi>
      </n-grid>

      <!-- Task queue -->
      <n-card title="My GPU Tasks">
        <template #header-extra>
          <n-button size="small" @click="gpuStore.fetchQueue" :loading="gpuStore.loading">Refresh</n-button>
        </template>
        <n-data-table
          :columns="columns"
          :data="gpuStore.queue"
          :pagination="{ pageSize: 10 }"
          size="small"
          striped
        />
        <n-empty v-if="!gpuStore.queue.length && !gpuStore.loading" description="No GPU tasks" />
      </n-card>
    </n-space>
  </div>
</template>

<script setup>
import { computed, h, onMounted, onUnmounted } from 'vue'
import { NTag } from 'naive-ui'
import { useGpuStore } from '../stores/gpu'

const gpuStore = useGpuStore()

const usedPct = computed(() => {
  const { used_slots, total_slots } = gpuStore.pool
  if (!total_slots) return 0
  return Math.round((used_slots / total_slots) * 100)
})

const usedTagType = computed(() => {
  if (usedPct.value >= 100) return 'error'
  if (usedPct.value >= 75) return 'warning'
  return 'success'
})

const statusTypeMap = { pending: 'warning', running: 'info', done: 'success', failed: 'error', cancelled: 'default' }

const columns = [
  { title: 'Type', key: 'task_type', width: 80,
    render: (r) => h(NTag, { size: 'small', type: r.task_type === 'search' ? 'info' : 'warning', round: true }, { default: () => r.task_type }) },
  { title: 'Status', key: 'status', width: 100,
    render: (r) => h(NTag, { size: 'small', type: statusTypeMap[r.status] || 'default', round: true }, { default: () => r.status }) },
  { title: 'GPU Slots', key: 'gpu_slots', width: 90 },
  { title: 'Submitted', key: 'submitted_at', render: (r) => r.submitted_at ? new Date(r.submitted_at).toLocaleTimeString() : '—' },
  { title: 'Started', key: 'started_at', render: (r) => r.started_at ? new Date(r.started_at).toLocaleTimeString() : '—' },
  { title: 'GPU Seconds', key: 'gpu_seconds', width: 110, render: (r) => r.gpu_seconds?.toFixed(1) || '—' },
]

let timer = null
onMounted(() => {
  gpuStore.fetchQueue()
  timer = setInterval(() => gpuStore.fetchQueue(), 3000)
})
onUnmounted(() => clearInterval(timer))
</script>
