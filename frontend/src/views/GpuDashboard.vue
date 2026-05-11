<template>
  <div>
    <n-space vertical :size="20">
      <n-grid :cols="3" :x-gap="16">
        <n-gi>
          <n-card size="small">
            <n-statistic :label="t('gpu.totalSlots')" :value="gpuStore.pool.total_slots" />
          </n-card>
        </n-gi>
        <n-gi>
          <n-card size="small">
            <n-statistic :label="t('gpu.usedSlots')" :value="gpuStore.pool.used_slots">
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
            <n-statistic :label="t('gpu.availableSlots')" :value="gpuStore.pool.available_slots" />
          </n-card>
        </n-gi>
      </n-grid>

      <n-card>
        <n-tabs type="line" animated>
          <n-tab-pane name="active" :tab="t('gpu.activeTasks')">
            <template #tab>
              <n-space :size="8" align="center">
                <span>{{ t('gpu.activeTasks') }}</span>
                <n-badge :value="gpuStore.queue.length" :max="99" />
              </n-space>
            </template>
            <n-space vertical :size="12">
              <n-space justify="space-between">
                <n-text depth="3">{{ t('gpu.autoRefresh') }}</n-text>
                <n-button size="small" @click="gpuStore.fetchQueue" :loading="gpuStore.loading">
                  {{ t('gpu.btnRefresh') }}
                </n-button>
              </n-space>
              <n-data-table
                :columns="activeColumns"
                :data="gpuStore.queue"
                :pagination="{ pageSize: 10 }"
                size="small"
                striped
              />
            </n-space>
          </n-tab-pane>

          <n-tab-pane name="history" :tab="t('gpu.taskHistory')">
            <n-space vertical :size="16">
              <n-space :size="12" align="center" wrap>
                <n-select
                  v-model:value="filters.status_filter"
                  :options="statusOptions"
                  :placeholder="t('gpu.filterStatus')"
                  clearable
                  multiple
                  style="width: 100px"
                  size="small"
                />
                <n-select
                  v-model:value="filters.task_type_filter"
                  :options="typeOptions"
                  :placeholder="t('gpu.filterType')"
                  clearable
                  style="width: 100px"
                  size="small"
                />
                <n-date-picker
                  v-model:value="filters.dateRange"
                  type="datetimerange"
                  clearable
                  :start-placeholder="t('gpu.filterDateRangeStart')"
                  :end-placeholder="t('gpu.filterDateRangeEnd')"
                  style="min-width: 150px"
                  size="small"
                />
                <n-input
                  v-model:value="filters.task_id_filter"
                  :placeholder="t('gpu.filterTaskId')"
                  clearable
                  size="small"
                />
                <n-input
                  v-if="isAdmin"
                  v-model:value="filters.username_filter"
                  :placeholder="t('gpu.filterUsername')"
                  clearable
                  style="width: 120px"
                  size="small"
                />
                <n-button type="primary" size="small" @click="applyFilters" :loading="gpuStore.historyLoading">
                  {{ t('gpu.btnApply') }}
                </n-button>
                <n-button size="small" @click="resetFilters">
                  {{ t('gpu.btnReset') }}
                </n-button>
              </n-space>

              <n-data-table
                :columns="historyColumns"
                :data="gpuStore.historyTasks"
                :pagination="paginationProps"
                size="small"
                striped
                @update:page="handlePageChange"
                @update:page-size="handlePageSizeChange"
              />
            </n-space>
          </n-tab-pane>
        </n-tabs>
      </n-card>
    </n-space>
  </div>
</template>

<script setup>
import { computed, h, onMounted, onUnmounted, ref } from 'vue'
import { NTag, NButton, NPopconfirm } from 'naive-ui'
import { useGpuStore } from '../stores/gpu'
import { useAuthStore } from '../stores/auth'
import { useI18n } from '../i18n/index.js'

const { t } = useI18n()
const gpuStore = useGpuStore()
const authStore = useAuthStore()

const isAdmin = computed(() => authStore.user?.role === 'admin')

const filters = ref({
  status_filter: null,
  task_type_filter: null,
  task_id_filter: null,
  username_filter: null,
  dateRange: null
})

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

const statusTypeMap = {
  pending: 'default',
  running: 'info',
  done: 'success',
  failed: 'error',
  cancelled: 'warning'
}

const statusOptions = [
  { label: 'Done', value: 'done' },
  { label: 'Failed', value: 'failed' },
  { label: 'Cancelled', value: 'cancelled' }
]

const typeOptions = [
  { label: 'Search', value: 'search' },
  { label: 'Build', value: 'build' }
]

const activeColumns = computed(() => [
  { title: t('gpu.col.type'), key: 'task_type', width: 80,
    render: (r) => h(NTag, { size: 'small', type: r.task_type === 'search' ? 'info' : 'warning', round: true }, { default: () => r.task_type }) },
  { title: t('gpu.col.status'), key: 'status', width: 80,
    render: (r) => h(NTag, { size: 'small', type: statusTypeMap[r.status] || 'default', round: true }, { default: () => r.status }) },
  { title: t('gpu.col.slots'), key: 'gpu_slots', width: 90 },
  { title: t('gpu.col.submitted'), key: 'submitted_at', width:160, render: (r) => r.submitted_at ? new Date(r.submitted_at).toLocaleString() : '—' },
  { title: t('gpu.col.started'), key: 'started_at', width:160, render: (r) => r.started_at ? new Date(r.started_at).toLocaleString() : '—' },
  { title: t('gpu.col.gpuSeconds'), key: 'gpu_seconds', width: 110, render: (r) => r.gpu_seconds?.toFixed(1) || '—' },
  {
    title: t('gpu.col.actions'),
    key: 'actions',
    width: 80,
    render: (r) => (r.status === 'pending' || r.status === 'running') ? h(NPopconfirm, {
      onPositiveClick: () => handleCancel(r.id),
    }, {
      trigger: () => h(NButton, { size: 'small', type: 'error', secondary: true }, { default: () => t('gpu.btnCancel') }),
      default: () => t('gpu.confirmCancel'),
    }) : null,
  }
])

const historyColumns = computed(() => {
  const cols = [
    { title: 'ID', key: 'id', width: 240, ellipsis: { tooltip: true } },
    { title: t('gpu.col.type'), key: 'task_type', width: 80,
      render: (r) => h(NTag, { size: 'small', type: r.task_type === 'search' ? 'info' : 'warning', round: true }, { default: () => r.task_type }) },
    { title: t('gpu.col.status'), key: 'status', width: 80,
      render: (r) => h(NTag, { size: 'small', type: statusTypeMap[r.status] || 'default', round: true }, { default: () => r.status }) },
    { title: t('gpu.col.submitted'), key: 'submitted_at', width: 160, render: (r) => r.submitted_at ? new Date(r.submitted_at).toLocaleString() : '—' },
    { title: t('gpu.col.completed'), key: 'completed_at', width: 160, render: (r) => r.completed_at ? new Date(r.completed_at).toLocaleString() : '—' },
    { title: t('gpu.col.gpuSeconds'), key: 'gpu_seconds', width: 110, render: (r) => r.gpu_seconds?.toFixed(1) || '—' }
  ]
  if (isAdmin.value) {
    cols.splice(1, 0, { title: t('users.col.username'), key: 'username', width: 100 })
  }
  return cols
})

const paginationProps = computed(() => ({
  page: Math.floor(gpuStore.historyFilters.offset / gpuStore.historyFilters.limit) + 1,
  pageSize: gpuStore.historyFilters.limit,
  itemCount: gpuStore.historyTotal,
  pageSizes: [20, 50, 100],
  showSizePicker: true
}))

function applyFilters() {
  const hasAnyFilter = filters.value.status_filter?.length || filters.value.task_type_filter ||
                       filters.value.task_id_filter || filters.value.username_filter || filters.value.dateRange

  if (!hasAnyFilter) {
    resetFilters()
    return
  }

  const params = { offset: 0, limit: gpuStore.historyFilters.limit }
  if (filters.value.status_filter?.length) {
    params.status_filter = filters.value.status_filter
  }
  if (filters.value.task_type_filter) {
    params.task_type_filter = filters.value.task_type_filter
  }
  if (filters.value.task_id_filter) {
    params.task_id_filter = filters.value.task_id_filter
  }
  if (filters.value.username_filter) {
    params.username_filter = filters.value.username_filter
  }
  if (filters.value.dateRange) {
    params.start_date = new Date(filters.value.dateRange[0]).toISOString()
    params.end_date = new Date(filters.value.dateRange[1]).toISOString()
  }
  gpuStore.setHistoryFilters(params)
  gpuStore.fetchHistory()
}

function resetFilters() {
  filters.value = {
    status_filter: null,
    task_type_filter: null,
    task_id_filter: null,
    username_filter: null,
    dateRange: null
  }
  gpuStore.resetHistoryFilters()
  gpuStore.fetchHistory()
}

function handlePageChange(page) {
  const offset = (page - 1) * gpuStore.historyFilters.limit
  gpuStore.setHistoryFilters({ offset })
  gpuStore.fetchHistory()
}

function handlePageSizeChange(pageSize) {
  gpuStore.setHistoryFilters({ limit: pageSize, offset: 0 })
  gpuStore.fetchHistory()
}

async function handleCancel(id) {
  try {
    await gpuStore.cancelTask(id)
    await gpuStore.fetchQueue()
    window.$message?.success(t('gpu.msgCancelled'))
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Cancel failed')
  }
}

let timer = null
onMounted(() => {
  gpuStore.fetchQueue()
  gpuStore.fetchHistory()
  timer = setInterval(() => gpuStore.fetchQueue(), 3000)
})
onUnmounted(() => clearInterval(timer))
</script>
