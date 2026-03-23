<template>
  <div>
    <n-space vertical :size="20">
      <n-card>
        <n-space justify="space-between" align="center">
          <n-space align="center">
            <n-text v-if="activeDatasetId" depth="2">
              {{ t('datasets.active') }} <n-text strong>{{ activeName }}</n-text>
            </n-text>
            <n-text v-else depth="3">{{ t('datasets.noActive') }}</n-text>
          </n-space>
          <n-space>
            <n-button size="small" type="primary" secondary @click="showImportModal = true">
              {{ t('datasets.btnImport') }}
            </n-button>
            <n-button size="small" @click="refresh" :loading="loading">{{ t('datasets.btnRefresh') }}</n-button>
          </n-space>
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

      <n-empty v-else-if="!loading" :description="t('datasets.empty')" />
    </n-space>

    <!-- Export Modal -->
    <n-modal v-model:show="showExportModal" preset="card" :title="t('datasets.export.title')" style="max-width: 400px">
      <n-space vertical :size="16">
        <n-text depth="2">{{ t('datasets.export.hint') }}</n-text>
        <n-space justify="end">
          <n-button @click="showExportModal = false">{{ t('datasets.export.btnCancel') }}</n-button>
          <n-button type="primary" @click="startExport" :loading="exportLoading">
            {{ t('datasets.export.btnStart') }}
          </n-button>
        </n-space>
      </n-space>
    </n-modal>

    <!-- Import Modal -->
    <n-modal v-model:show="showImportModal" preset="card" :title="t('datasets.import.title')" style="max-width: 480px">
      <n-space vertical :size="16">
        <n-text depth="2">{{ t('datasets.import.hint') }}</n-text>
        <n-upload
          ref="uploadRef"
          accept=".7z"
          :max="1"
          :default-upload="false"
          @change="onImportFileChange"
        >
          <n-upload-dragger>
            <n-text>{{ t('datasets.import.dragHint') }}</n-text>
          </n-upload-dragger>
        </n-upload>
        <n-input
          v-model:value="importName"
          :placeholder="t('datasets.import.namePlaceholder')"
          clearable
        />
        <n-progress
          v-if="importProgress.active"
          type="line"
          :percentage="importProgress.pct"
          :status="importProgress.status"
          :indicator-placement="'inside'"
        >
          {{ importProgress.step }}
        </n-progress>
        <n-alert v-if="importProgress.error" type="error" :title="importProgress.error" />
        <n-space justify="end">
          <n-button @click="cancelImport">{{ t('datasets.import.btnCancel') }}</n-button>
          <n-button
            type="primary"
            :disabled="!importFile || importProgress.active"
            :loading="importProgress.active"
            @click="startImport"
          >
            {{ t('datasets.import.btnStart') }}
          </n-button>
        </n-space>
      </n-space>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, h, onMounted, onUnmounted } from 'vue'
import { NTag, NButton, NSpace, NSwitch, NPopconfirm, NProgress } from 'naive-ui'
import {
  listDatasets, switchDataset, deleteDataset, setDatasetVisibility,
  exportDataset, getExportStatus, downloadExport,
  importDataset, getImportStatus,
} from '../api/buildApi'
import { useI18n } from '../i18n/index.js'

const { t } = useI18n()

const datasets = ref([])
const activeDatasetId = ref(null)
const loading = ref(false)
const error = ref('')

// Export state
const showExportModal = ref(false)
const exportLoading = ref(false)
const exportingDatasetId = ref(null)
let exportPollTimer = null

// Import state
const showImportModal = ref(false)
const importFile = ref(null)
const importName = ref('')
const importProgress = ref({ active: false, pct: 0, step: '', status: 'default', error: '' })
let importPollTimer = null

const activeName = computed(() => {
  const ds = datasets.value.find(d => d.id === activeDatasetId.value)
  return ds?.name || activeDatasetId.value
})

function rowClass(row) {
  return row.id === activeDatasetId.value ? 'row-active' : ''
}

const columns = computed(() => [
  {
    title: t('datasets.col.name'),
    key: 'name',
    render: (row) => {
      const parts = [h('span', row.name)]
      if (row.id === activeDatasetId.value) {
        parts.push(h(NTag, { type: 'success', size: 'small', round: true, style: 'margin-left: 6px' }, { default: () => t('datasets.tag.active') }))
      }
      return h(NSpace, { align: 'center', size: 4 }, { default: () => parts })
    },
  },
  {
    title: t('datasets.col.algorithm'),
    key: 'algorithm',
    width: 100,
    render: (row) => h(NTag, { size: 'small', round: true }, { default: () => row.algorithm }),
  },
  {
    title: t('datasets.col.status'),
    key: 'status',
    width: 130,
    render: (row) => {
      const typeMap = { ready: 'success', building: 'warning', importing: 'warning', error: 'error' }
      const parts = [h(NTag, { type: typeMap[row.status] || 'default', size: 'small', round: true }, { default: () => row.status })]
      if (row.status === 'building' || row.status === 'importing') {
        parts.push(h('span', { style: 'font-size: 0.8rem; color: #888; margin-left: 4px' }, `${row.progress_pct}%`))
      }
      return h(NSpace, { align: 'center', size: 4 }, { default: () => parts })
    },
  },
  {
    title: t('datasets.col.sequences'),
    key: 'num_indexed',
    width: 110,
    render: (row) => (row.num_indexed || row.num_sequences || 0).toLocaleString(),
  },
  {
    title: t('datasets.col.visibility'),
    key: 'visibility',
    width: 110,
    render: (row) => h(NSwitch, {
      value: row.visibility === 'public',
      size: 'small',
      checkedChildren: t('datasets.vis.public'),
      uncheckedChildren: t('datasets.vis.private'),
      onUpdateValue: (val) => handleVisibility(row, val ? 'public' : 'private'),
    }),
  },
  {
    title: t('datasets.col.created'),
    key: 'created_at',
    width: 160,
    render: (row) => row.created_at ? new Date(row.created_at).toLocaleString() : '—',
  },
  {
    title: t('datasets.col.actions'),
    key: 'actions',
    width: 210,
    render: (row) => h(NSpace, { size: 6 }, {
      default: () => [
        h(NButton, {
          size: 'small',
          type: 'primary',
          disabled: row.status !== 'ready' || row.id === activeDatasetId.value || loading.value,
          onClick: () => handleSwitch(row.id),
        }, { default: () => t('datasets.btn.use') }),
        h(NButton, {
          size: 'small',
          type: 'info',
          secondary: true,
          disabled: row.status !== 'ready' || loading.value,
          onClick: () => openExportModal(row.id),
        }, { default: () => t('datasets.btn.export') }),
        h(NPopconfirm, {
          onPositiveClick: () => handleDelete(row),
        }, {
          trigger: () => h(NButton, {
            size: 'small', type: 'error', secondary: true, disabled: loading.value,
          }, { default: () => t('datasets.btn.delete') }),
          default: () => t('datasets.confirm.delete', { name: row.name }),
        }),
      ],
    }),
  },
])

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
    window.$message?.success(t('datasets.msg.activated'))
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
    window.$message?.success(t('datasets.msg.deleted'))
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

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

function openExportModal(datasetId) {
  exportingDatasetId.value = datasetId
  showExportModal.value = true
}

async function startExport() {
  if (!exportingDatasetId.value) return
  exportLoading.value = true
  try {
    await exportDataset(exportingDatasetId.value)
    showExportModal.value = false
    window.$message?.info(t('datasets.export.started'))
    pollExportUntilDone(exportingDatasetId.value)
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Export failed to start')
  }
  exportLoading.value = false
}

function pollExportUntilDone(datasetId) {
  clearInterval(exportPollTimer)
  exportPollTimer = setInterval(async () => {
    try {
      const status = await getExportStatus(datasetId)
      if (status.status === 'done') {
        clearInterval(exportPollTimer)
        exportPollTimer = null
        window.$message?.success(t('datasets.export.done'))
        // Download via axios to carry the Authorization header
        await downloadExport(datasetId, `${status.dataset_name || 'export'}.7z`)
      } else if (status.status === 'error') {
        clearInterval(exportPollTimer)
        exportPollTimer = null
        window.$message?.error(t('datasets.export.failed'))
      }
    } catch (_) {
      clearInterval(exportPollTimer)
      exportPollTimer = null
    }
  }, 2000)
}

// ---------------------------------------------------------------------------
// Import
// ---------------------------------------------------------------------------

function onImportFileChange({ fileList }) {
  importFile.value = fileList[0]?.file || null
}

function cancelImport() {
  clearInterval(importPollTimer)
  importPollTimer = null
  importProgress.value = { active: false, pct: 0, step: '', status: 'default', error: '' }
  importFile.value = null
  importName.value = ''
  showImportModal.value = false
}

async function startImport() {
  if (!importFile.value) return
  importProgress.value = { active: true, pct: 0, step: 'uploading…', status: 'default', error: '' }

  const formData = new FormData()
  formData.append('file', importFile.value)
  formData.append('name', importName.value || '')

  try {
    const result = await importDataset(formData)
    const datasetId = result.dataset_id
    importProgress.value = { active: true, pct: 5, step: 'importing…', status: 'default', error: '' }
    pollImportUntilDone(datasetId)
  } catch (e) {
    const msg = e.response?.data?.detail || 'Import failed'
    importProgress.value = { active: false, pct: 0, step: '', status: 'error', error: msg }
  }
}

function pollImportUntilDone(datasetId) {
  clearInterval(importPollTimer)
  importPollTimer = setInterval(async () => {
    try {
      const status = await getImportStatus(datasetId)
      const pct = status.progress_pct || 0
      const step = status.progress_step || ''
      if (status.status === 'ready') {
        clearInterval(importPollTimer)
        importPollTimer = null
        importProgress.value = { active: false, pct: 100, step: 'done', status: 'success', error: '' }
        window.$message?.success(t('datasets.import.done'))
        await refresh()
        setTimeout(cancelImport, 1500)
      } else if (status.status === 'error') {
        clearInterval(importPollTimer)
        importPollTimer = null
        importProgress.value = {
          active: false, pct, step, status: 'error',
          error: status.error_msg || 'Import failed',
        }
      } else {
        importProgress.value = { active: true, pct, step, status: 'default', error: '' }
      }
    } catch (_) {
      clearInterval(importPollTimer)
      importPollTimer = null
    }
  }, 2000)
}

onMounted(refresh)
onUnmounted(() => {
  clearInterval(exportPollTimer)
  clearInterval(importPollTimer)
})
</script>

<style>
.row-active td { background: rgba(24, 160, 88, 0.06) !important; }
</style>
