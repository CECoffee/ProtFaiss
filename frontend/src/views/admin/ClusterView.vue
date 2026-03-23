<template>
  <div>
    <n-card :title="t('cluster.title')">
      <template #header-extra>
        <n-space align="center">
          <n-switch v-model:value="autoRefresh" size="small">
            <template #checked>{{ t('cluster.autoRefresh') }}</template>
            <template #unchecked>{{ t('cluster.autoRefresh') }}</template>
          </n-switch>
          <n-button size="small" @click="loadWorkers" :loading="loading">
            {{ t('cluster.btnRefresh') }}
          </n-button>
        </n-space>
      </template>

      <n-data-table
        :columns="columns"
        :data="workers"
        :pagination="false"
        :scroll-x="1500"
        size="small"
        striped
        :row-key="(r) => r.node_id"
      />
      <n-empty v-if="!workers.length && !loading" :description="t('cluster.empty')" style="margin-top: 16px" />
    </n-card>
  </div>
</template>

<script setup>
import { ref, computed, h, onMounted, onUnmounted } from 'vue'
import { NTag, NButton, NPopconfirm, NProgress, NSpace, NTooltip, NText } from 'naive-ui'
import { listWorkers, setWorkerStatus, setWorkerHidden } from '../../api/clusterApi'
import { useI18n } from '../../i18n/index.js'

const { t } = useI18n()

const workers = ref([])
const loading = ref(false)
const autoRefresh = ref(true)
let timer = null

// ─── Helpers ────────────────────────────────────────────────────────────────

function statusType(status) {
  if (status === 'online') return 'success'
  if (status === 'dead') return 'error'
  return 'warning'
}

function adminStatusType(s) {
  if (s === 'available') return 'success'
  if (s === 'unavailable') return 'warning'
  return 'default'
}

function relativeTime(ts) {
  if (!ts) return '—'
  const diff = Math.round(Date.now() / 1000 - ts)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

function fmtMb(mb) {
  if (mb < 0) return 'N/A'
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`
  return `${mb} MB`
}

function pct(v) {
  return v < 0 ? null : Math.min(100, Math.round(v))
}

// ─── Actions ────────────────────────────────────────────────────────────────

async function handleToggleStatus(worker) {
  const newStatus = worker.admin_status === 'unavailable' ? 'available' : 'unavailable'
  try {
    await setWorkerStatus(worker.node_id, newStatus)
    await loadWorkers()
    window.$message?.success(t('cluster.msg.statusUpdated'))
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Failed')
  }
}

async function handleToggleHidden(worker) {
  const nowHidden = worker.admin_status !== 'hidden'
  try {
    await setWorkerHidden(worker.node_id, nowHidden)
    await loadWorkers()
    window.$message?.success(t('cluster.msg.hiddenUpdated'))
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Failed')
  }
}

// ─── Columns ────────────────────────────────────────────────────────────────

const columns = computed(() => [
  {
    title: t('cluster.col.nodeId'),
    key: 'node_id',
    width: 160,
    ellipsis: { tooltip: true },
  },
  {
    title: t('cluster.col.address'),
    key: 'address',
    width: 150,
    ellipsis: { tooltip: true },
  },
  {
    title: t('cluster.col.status'),
    key: 'status',
    width: 90,
    render: (r) => h(NTag, { size: 'small', type: statusType(r.status), round: true }, {
      default: () => t(`cluster.status.${r.status}`) || r.status,
    }),
  },
  {
    title: t('cluster.col.adminStatus'),
    key: 'admin_status',
    width: 110,
    render: (r) => h(NTag, { size: 'small', type: adminStatusType(r.admin_status), round: true }, {
      default: () => t(`cluster.status.${r.admin_status}`) || r.admin_status,
    }),
  },
  {
    title: t('cluster.col.gpuSlots'),
    key: 'gpu_slots',
    width: 80,
    render: (r) => `${r.gpu_count} GPU / ${r.gpu_slots} slots`,
  },
  {
    title: t('cluster.col.cpu'),
    key: 'cpu',
    width: 100,
    render: (r) => {
      const v = pct(r.metrics?.cpu_percent)
      if (v === null) return h(NText, { depth: 3 }, { default: () => 'N/A' })
      return h(NTooltip, {}, {
        trigger: () => h(NProgress, { type: 'line', percentage: v, height: 8, borderRadius: 4, fillBorderRadius: 0, indicatorPlacement: 'inside' }),
        default: () => `CPU: ${v}%`,
      })
    },
  },
  {
    title: t('cluster.col.memory'),
    key: 'memory',
    width: 130,
    render: (r) => {
      const used = r.metrics?.memory_used_mb
      const total = r.metrics?.memory_total_mb
      const p = pct(r.metrics?.memory_percent)
      if (p === null || used == null || used < 0) return h(NText, { depth: 3 }, { default: () => 'N/A' })
      return h(NTooltip, {}, {
        trigger: () => h(NProgress, { type: 'line', percentage: p, height: 8, borderRadius: 4, fillBorderRadius: 0, indicatorPlacement: 'inside' }),
        default: () => `${fmtMb(used)} / ${fmtMb(total)} (${p}%)`,
      })
    },
  },
  {
    title: t('cluster.col.gpu'),
    key: 'gpu_util',
    width: 130,
    render: (r) => {
      const gpus = r.metrics?.gpus
      if (!gpus || !gpus.length) return h(NText, { depth: 3 }, { default: () => 'N/A' })
      const avg = gpus.reduce((s, g) => s + (g.utilization_percent >= 0 ? g.utilization_percent : 0), 0) / gpus.length
      const p = pct(avg)
      return h(NTooltip, {}, {
        trigger: () => h(NProgress, { type: 'line', percentage: p, height: 8, borderRadius: 4, fillBorderRadius: 0, indicatorPlacement: 'inside' }),
        default: () => gpus.map((g, i) => `GPU${i}: ${g.utilization_percent >= 0 ? g.utilization_percent + '%' : 'N/A'}${g.temperature_c >= 0 ? ' ' + g.temperature_c + '°C' : ''}`).join(' | '),
      })
    },
  },
  {
    title: t('cluster.col.vram'),
    key: 'vram',
    width: 140,
    render: (r) => {
      const gpus = r.metrics?.gpus
      if (!gpus || !gpus.length) return h(NText, { depth: 3 }, { default: () => 'N/A' })
      return h(NSpace, { vertical: true, size: 2 }, {
        default: () => gpus.map((g, i) => {
          const p = pct(g.vram_percent)
          if (p === null) return h(NText, { depth: 3, key: i }, { default: () => `GPU${i}: N/A` })
          return h(NTooltip, { key: i }, {
            trigger: () => h(NProgress, { type: 'line', percentage: p, height: 6, borderRadius: 4, fillBorderRadius: 0, indicatorPlacement: 'inside' }),
            default: () => `GPU${i}: ${fmtMb(g.vram_used_mb)} / ${fmtMb(g.vram_total_mb)}`,
          })
        }),
      })
    },
  },
  {
    title: t('cluster.col.cached'),
    key: 'cached_datasets',
    width: 80,
    render: (r) => r.cached_datasets?.length ?? 0,
  },
  {
    title: t('cluster.col.tasks'),
    key: 'running_tasks',
    width: 70,
  },
  {
    title: t('cluster.col.lastSeen'),
    key: 'last_seen',
    width: 100,
    render: (r) => relativeTime(r.last_seen),
  },
  {
    title: t('cluster.col.actions'),
    key: 'actions',
    width: 190,
    render: (r) => h(NSpace, { size: 'small' }, {
      default: () => [
        // Drain / Undrain
        h(NPopconfirm, {
          onPositiveClick: () => handleToggleStatus(r),
        }, {
          trigger: () => h(NButton, {
            size: 'small',
            type: r.admin_status === 'unavailable' ? 'success' : 'warning',
            secondary: true,
          }, {
            default: () => r.admin_status === 'unavailable' ? t('cluster.btn.undrain') : t('cluster.btn.drain'),
          }),
          default: () => r.admin_status === 'unavailable' ? t('cluster.confirm.undrain') : t('cluster.confirm.drain'),
        }),
        // Hide / Unhide
        h(NPopconfirm, {
          onPositiveClick: () => handleToggleHidden(r),
        }, {
          trigger: () => h(NButton, {
            size: 'small',
            type: r.admin_status === 'hidden' ? 'info' : 'default',
            secondary: true,
          }, {
            default: () => r.admin_status === 'hidden' ? t('cluster.btn.unhide') : t('cluster.btn.hide'),
          }),
          default: () => r.admin_status === 'hidden' ? t('cluster.confirm.unhide') : t('cluster.confirm.hide'),
        }),
      ],
    }),
  },
])

// ─── Data loading ────────────────────────────────────────────────────────────

async function loadWorkers() {
  loading.value = true
  try {
    const data = await listWorkers()
    workers.value = data.workers || []
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Failed to load workers')
  }
  loading.value = false
}

onMounted(() => {
  loadWorkers()
  timer = setInterval(() => {
    if (autoRefresh.value) loadWorkers()
  }, 5000)
})

onUnmounted(() => clearInterval(timer))
</script>
