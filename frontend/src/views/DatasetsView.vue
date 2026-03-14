<template>
  <div>
    <n-space vertical :size="20">
      <n-card>
        <n-space justify="space-between" align="center">
          <n-space align="center">
            <n-text v-if="activeDatasetId" depth="2">
              Active: <n-text strong>{{ activeName }}</n-text>
            </n-text>
            <n-text v-else depth="3">No active dataset</n-text>
          </n-space>
          <n-button size="small" @click="refresh" :loading="loading">Refresh</n-button>
        </n-space>
      </n-card>

      <n-alert v-if="error" type="error" :title="error" />

      <n-data-table
        v-if="datasets.length > 0"
        :columns="columns"
        :data="datasets"
        :pagination="{ pageSize: 15 }"
        :row-class-name="rowClass"
        size="small"
        striped
      />

      <n-empty v-else-if="!loading" description="No datasets yet. Go to Build Index to create one." />
    </n-space>
  </div>
</template>

<script setup>
import { ref, computed, h, onMounted } from 'vue'
import { NTag, NButton, NSpace, NSwitch, NPopconfirm } from 'naive-ui'
import { listDatasets, switchDataset, deleteDataset, setDatasetVisibility } from '../api/buildApi'

const datasets = ref([])
const activeDatasetId = ref(null)
const loading = ref(false)
const error = ref('')

const activeName = computed(() => {
  const ds = datasets.value.find(d => d.id === activeDatasetId.value)
  return ds?.name || activeDatasetId.value
})

function rowClass(row) {
  return row.id === activeDatasetId.value ? 'row-active' : ''
}

const columns = [
  {
    title: 'Name',
    key: 'name',
    render: (row) => {
      const parts = [h('span', row.name)]
      if (row.id === activeDatasetId.value) {
        parts.push(h(NTag, { type: 'success', size: 'small', round: true, style: 'margin-left: 6px' }, { default: () => 'Active' }))
      }
      return h(NSpace, { align: 'center', size: 4 }, { default: () => parts })
    },
  },
  {
    title: 'Algorithm',
    key: 'algorithm',
    width: 100,
    render: (row) => h(NTag, { size: 'small', round: true }, { default: () => row.algorithm }),
  },
  {
    title: 'Status',
    key: 'status',
    width: 130,
    render: (row) => {
      const typeMap = { ready: 'success', building: 'warning', error: 'error' }
      const parts = [h(NTag, { type: typeMap[row.status] || 'default', size: 'small', round: true }, { default: () => row.status })]
      if (row.status === 'building') {
        parts.push(h('span', { style: 'font-size: 0.8rem; color: #888; margin-left: 4px' }, `${row.progress_pct}%`))
      }
      return h(NSpace, { align: 'center', size: 4 }, { default: () => parts })
    },
  },
  {
    title: 'Sequences',
    key: 'num_indexed',
    width: 110,
    render: (row) => (row.num_indexed || row.num_sequences || 0).toLocaleString(),
  },
  {
    title: 'Visibility',
    key: 'visibility',
    width: 110,
    render: (row) => h(NSwitch, {
      value: row.visibility === 'public',
      size: 'small',
      checkedChildren: 'Public',
      uncheckedChildren: 'Private',
      onUpdateValue: (val) => handleVisibility(row, val ? 'public' : 'private'),
    }),
  },
  {
    title: 'Created',
    key: 'created_at',
    width: 160,
    render: (row) => row.created_at ? new Date(row.created_at).toLocaleString() : '—',
  },
  {
    title: 'Actions',
    key: 'actions',
    width: 160,
    render: (row) => h(NSpace, { size: 6 }, {
      default: () => [
        h(NButton, {
          size: 'small',
          type: 'primary',
          disabled: row.status !== 'ready' || row.id === activeDatasetId.value || loading.value,
          onClick: () => handleSwitch(row.id),
        }, { default: () => 'Use' }),
        h(NPopconfirm, {
          onPositiveClick: () => handleDelete(row),
        }, {
          trigger: () => h(NButton, {
            size: 'small',
            type: 'error',
            secondary: true,
            disabled: loading.value,
          }, { default: () => 'Delete' }),
          default: () => `Delete "${row.name}"? This will remove index files and the database table.`,
        }),
      ],
    }),
  },
]

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const data = await listDatasets()
    datasets.value = data.datasets || []
    activeDatasetId.value = data.active_dataset_id
  } catch (e) {
    error.value = e.response?.data?.detail || 'Failed to load datasets'
  }
  loading.value = false
}

async function handleSwitch(id) {
  loading.value = true
  try {
    await switchDataset(id)
    activeDatasetId.value = id
    window.$message?.success('Dataset activated')
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Switch failed')
  }
  loading.value = false
}

async function handleDelete(ds) {
  loading.value = true
  try {
    await deleteDataset(ds.id)
    await refresh()
    window.$message?.success('Dataset deleted')
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Delete failed')
  }
  loading.value = false
}

async function handleVisibility(ds, visibility) {
  try {
    await setDatasetVisibility(ds.id, visibility)
    ds.visibility = visibility
    window.$message?.success(`Set to ${visibility}`)
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Update failed')
  }
}

onMounted(refresh)
</script>

<style>
.row-active td { background: rgba(24, 160, 88, 0.06) !important; }
</style>
