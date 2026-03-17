<template>
  <div>
    <n-space vertical :size="20">
      <!-- Dataset selector -->
      <n-card size="small">
        <n-space align="center" justify="space-between">
          <n-space align="center">
            <n-text strong>Active Dataset:</n-text>
            <n-select
              v-model:value="selectedDatasetId"
              :options="datasetOptions"
              placeholder="Select a dataset"
              style="min-width: 260px"
              :loading="dsLoading"
              @update:value="handleSwitch"
            />
          </n-space>
          <n-tag v-if="activeEntry" :type="activeEntry.status === 'ready' ? 'success' : 'warning'" round>
            {{ activeEntry.status }}
          </n-tag>
        </n-space>
      </n-card>

      <!-- Search form -->
      <n-card title="Protein Sequence Search">
        <n-space vertical :size="16">
          <n-form-item label="Sequence (FASTA or raw amino acids)" :show-feedback="false">
            <n-input
              v-model:value="sequence"
              type="textarea"
              :rows="5"
              placeholder=">protein_id&#10;MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKRQTLGQHDFSAGEGLYTHMKALRPDEDRLSPLHSVYVDQWDWERVMGDGERQFSTLKSTVEAIWAGIKATEAAVSEEFGLAPFLPDQIHFVHSQELLSRYPDLDAKGRERAIAKDLGAVFLVGIGGKLSDGHRHDVRAPDYDDWSTPSELGHAGLNGDILVWNPVLEDAFELSSMGIRVDADTLKHQLALTGDEDRLELEWHQALLRGEMPQTIGGGIGQSRLTMLLLQLPHIGQVQAGVWPAAVRESVPSLL"
              :disabled="status === 'pending'"
            />
          </n-form-item>

          <n-space>
            <n-form-item label="Top K" :show-feedback="false" style="width: 120px">
              <n-input-number v-model:value="topK" :min="1" :max="100" />
            </n-form-item>
            <n-form-item label="Pooling" :show-feedback="false" style="width: 140px">
              <n-select v-model:value="pooling" :options="poolingOptions" />
            </n-form-item>
          </n-space>

          <n-alert v-if="noDatasetError" type="warning" title="No active dataset. Please activate a dataset first." />

          <n-space>
            <n-button
              type="primary"
              :loading="status === 'pending'"
              :disabled="!sequence.trim() || status === 'pending'"
              @click="handleSubmit"
            >
              Search
            </n-button>
            <n-button v-if="status === 'pending'" @click="handleCancel">Cancel</n-button>
          </n-space>
        </n-space>
      </n-card>

      <!-- Status -->
      <n-card v-if="status !== 'idle'" size="small">
        <n-space align="center">
          <n-spin v-if="status === 'pending'" size="small" />
          <n-icon v-else-if="status === 'done'" color="#18a058" size="18"><CheckmarkCircleOutline /></n-icon>
          <n-icon v-else color="#d03050" size="18"><CloseCircleOutline /></n-icon>
          <n-text>{{ statusText }}</n-text>
          <template v-if="status === 'pending' && indexStatus === 'loading'">
            <n-divider vertical />
            <n-text depth="3" style="font-size: 0.8rem">Loading index from disk...</n-text>
          </template>
          <template v-if="meta">
            <n-divider vertical />
            <n-text depth="3" style="font-size: 0.8rem">
              ESM2: {{ meta.esm_time?.toFixed(2) }}s
              <template v-if="meta.index_load_time > 0"> | Index load: {{ meta.index_load_time?.toFixed(2) }}s</template>
              | FAISS: {{ meta.faiss_time?.toFixed(2) }}s | DB: {{ meta.db_time?.toFixed(2) }}s
            </n-text>
          </template>
        </n-space>
      </n-card>

      <!-- Results -->
      <n-card v-if="status === 'done' && result?.length" title="Results">
        <n-data-table
          :columns="resultColumns"
          :data="result"
          :pagination="{ pageSize: 10 }"
          size="small"
          striped
        />
      </n-card>
    </n-space>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { h } from 'vue'
import { NTag, NText, NTooltip, NEllipsis } from 'naive-ui'
import { CheckmarkCircleOutline, CloseCircleOutline } from '@vicons/ionicons5'
import { submitSearch, getResult } from '../api/proteinSearch'
import { listDatasets, switchDataset } from '../api/buildApi'

const sequence = ref('')
const topK = ref(5)
const pooling = ref('mean')
const status = ref('idle')
const taskId = ref(null)
const result = ref(null)
const meta = ref(null)
const indexStatus = ref('unknown')
const noDatasetError = ref(false)
const pollTimer = ref(null)

const datasets = ref([])
const activeDatasetId = ref(null)
const selectedDatasetId = ref(null)
const dsLoading = ref(false)

const poolingOptions = [
  { label: 'Mean', value: 'mean' },
  { label: 'CLS', value: 'cls' },
]

const activeEntry = computed(() => datasets.value.find(d => d.id === activeDatasetId.value))

const datasetOptions = computed(() =>
  datasets.value
    .filter(d => d.status === 'ready')
    .map(d => ({
      label: `${d.name} (${d.algorithm})`,
      value: d.id,
    }))
)

const statusText = computed(() => {
  if (status.value === 'pending') {
    if (indexStatus.value === 'loading') return `Loading index... (task: ${taskId.value?.slice(0, 8)})`
    return `Searching... (task: ${taskId.value?.slice(0, 8)})`
  }
  if (status.value === 'done') return `Done — ${result.value?.length || 0} results`
  if (status.value === 'error') return 'Search failed'
  return ''
})

const resultColumns = [
  { title: '#', key: 'id', width: 70 },
  {
    title: 'Header',
    key: 'header',
    render: (row) => h(NEllipsis, { style: 'max-width: 200px' }, { default: () => row.header || '—' }),
  },
  {
    title: 'Sequence',
    key: 'sequence',
    render: (row) => h(NEllipsis, { style: 'max-width: 180px' }, { default: () => row.sequence || '—' }),
  },
  { title: 'KO', key: 'ko', width: 90 },
  { title: 'EC', key: 'ec', width: 90 },
  {
    title: 'Distance',
    key: 'faiss_distance',
    width: 100,
    render: (row) => h(NTag, { type: 'info', size: 'small', round: true }, { default: () => row.faiss_distance?.toFixed(4) }),
  },
]

async function loadDatasets() {
  dsLoading.value = true
  try {
    const data = await listDatasets()
    datasets.value = data.datasets || []
    activeDatasetId.value = data.active_dataset_id
    selectedDatasetId.value = data.active_dataset_id
  } catch {}
  dsLoading.value = false
}

async function handleSwitch(id) {
  if (!id) return
  dsLoading.value = true
  try {
    await switchDataset(id)
    activeDatasetId.value = id
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Switch failed')
  }
  dsLoading.value = false
}

async function handleSubmit() {
  noDatasetError.value = false
  status.value = 'pending'
  result.value = null
  meta.value = null
  indexStatus.value = 'unknown'
  try {
    const id = await submitSearch(sequence.value, topK.value, pooling.value)
    taskId.value = id
    pollTimer.value = setInterval(() => pollResult(id), 1000)
  } catch (e) {
    if (e.response?.status === 409) {
      noDatasetError.value = true
    } else {
      window.$message?.error(e.response?.data?.detail || 'Submit failed')
    }
    status.value = 'idle'
  }
}

async function pollResult(id) {
  try {
    const task = await getResult(id)
    if (task.index_status) indexStatus.value = task.index_status
    if (task.status === 'done') {
      clearInterval(pollTimer.value)
      status.value = 'done'
      result.value = task.result
      meta.value = task.times
    } else if (task.status === 'error') {
      clearInterval(pollTimer.value)
      status.value = 'error'
      window.$message?.error(task.error || 'Search error')
    }
  } catch {}
}

function handleCancel() {
  clearInterval(pollTimer.value)
  status.value = 'idle'
  taskId.value = null
  indexStatus.value = 'unknown'
}

onMounted(loadDatasets)
</script>
