<template>
  <div>
    <n-space vertical :size="20">
      <!-- Dataset selector -->
      <n-card size="small">
        <n-space align="center" justify="space-between">
          <n-space align="center">
            <n-text strong>{{ t('search.activeDataset') }}</n-text>
            <n-select
              v-model:value="selectedDatasetId"
              :options="datasetOptions"
              :placeholder="t('search.selectDataset')"
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

      <n-tabs type="line" animated>
        <n-tab-pane name="search" :tab="t('search.tab.search')">
          <n-space vertical :size="16">
            <!-- Search form -->
            <n-card :title="t('search.title')">
              <n-space vertical :size="16">
                <n-form-item :label="t('search.seqLabel')" :show-feedback="false">
                  <n-input
                    v-model:value="sequence"
                    type="textarea"
                    :rows="5"
                    placeholder=">protein_id&#10;MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKRQTLGQHDFSAGEGLYTHMKALRPDEDRLSPLHSVYVDQWDWERVMGDGERQFSTLKSTVEAIWAGIKATEAAVSEEFGLAPFLPDQIHFVHSQELLSRYPDLDAKGRERAIAKDLGAVFLVGIGGKLSDGHRHDVRAPDYDDWSTPSELGHAGLNGDILVWNPVLEDAFELSSMGIRVDADTLKHQLALTGDEDRLELEWHQALLRGEMPQTIGGGIGQSRLTMLLLQLPHIGQVQAGVWPAAVRESVPSLL"
                    :disabled="status === 'pending'"
                  />
                </n-form-item>

                <n-space>
                  <n-form-item :label="t('search.topK')" :show-feedback="false" style="width: 120px">
                    <n-input-number v-model:value="topK" :min="1" :max="100" />
                  </n-form-item>
                  <n-form-item :label="t('search.pooling')" :show-feedback="false" style="width: 140px">
                    <n-select v-model:value="pooling" :options="poolingOptions" />
                  </n-form-item>
                </n-space>

                <n-alert v-if="noDatasetError" type="warning" :title="t('search.noDataset')" />
                <n-alert v-if="!gpuStore.gpuAvailable" type="error" :title="t('search.noGpu')" />

                <n-space>
                  <n-button
                    type="primary"
                    :loading="status === 'pending'"
                    :disabled="!sequence.trim() || status === 'pending' || !gpuStore.gpuAvailable"
                    @click="handleSubmit"
                  >
                    {{ t('search.btnSearch') }}
                  </n-button>
                  <n-button v-if="status === 'pending'" @click="handleCancel">{{ t('search.btnCancel') }}</n-button>
                </n-space>
              </n-space>
            </n-card>

            <!-- Progress steps -->
            <SearchProgress
              v-if="status !== 'idle'"
              :phase="phase"
              :times="meta"
              :error="errorMsg"
            />

            <!-- Results -->
            <n-card v-if="status === 'done' && result?.length" :title="t('search.results')">
              <n-data-table
                :columns="resultColumns"
                :data="result"
                :pagination="{ pageSize: 10 }"
                size="small"
                striped
              />
            </n-card>
          </n-space>
        </n-tab-pane>

        <n-tab-pane name="history" :tab="t('search.tab.history')">
          <SearchHistoryTab />
        </n-tab-pane>
      </n-tabs>
    </n-space>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { h } from 'vue'
import { NTag, NText, NEllipsis } from 'naive-ui'
import { submitSearch, getResult } from '../api/proteinSearch'
import { listDatasets, switchDataset } from '../api/buildApi'
import { useI18n } from '../i18n/index.js'
import { useGpuStore } from '../stores/gpu'
import SearchProgress from '../components/SearchProgress.vue'
import SearchHistoryTab from '../components/SearchHistoryTab.vue'

const { t } = useI18n()
const gpuStore = useGpuStore()

const sequence = ref('')
const topK = ref(5)
const pooling = ref('mean')
const status = ref('idle')
const phase = ref('pending')
const taskId = ref(null)
const result = ref(null)
const meta = ref(null)
const errorMsg = ref(null)
const noDatasetError = ref(false)
const pollTimer = ref(null)

const datasets = ref([])
const activeDatasetId = ref(null)
const selectedDatasetId = ref(null)
const dsLoading = ref(false)

const poolingOptions = computed(() => [
  { label: t('search.poolingMean'), value: 'mean' },
  { label: t('search.poolingCls'), value: 'cls' },
])

const activeEntry = computed(() => datasets.value.find(d => d.id === activeDatasetId.value))

const datasetOptions = computed(() =>
  datasets.value
    .filter(d => d.status === 'ready')
    .map(d => ({ label: `${d.name} (${d.algorithm})`, value: d.id }))
)

const resultColumns = computed(() => [
  { title: t('search.history.col.id'), key: 'id', width: 90 },
  {
    title: t('search.col.header'),
    key: 'header',
    render: (row) => h(NEllipsis, { style: 'max-width: 350px' }, { default: () => row.header || '—' }),
  },
  {
    title: t('search.col.sequence'),
    key: 'sequence',
    render: (row) => h(NEllipsis, { style: 'max-width: 350px' }, { default: () => row.sequence || '—' }),
  },
  { title: t('search.col.ko'), key: 'ko', width: 90 },
  { title: t('search.col.ec'), key: 'ec', width: 90 },
  {
    title: t('search.col.distance'),
    key: 'faiss_distance',
    width: 100,
    render: (row) => h(NTag, { type: 'info', size: 'small', round: true }, { default: () => row.faiss_distance?.toFixed(4) }),
  },
])

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
  phase.value = 'pending'
  result.value = null
  meta.value = null
  errorMsg.value = null
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
    // Map index_status / phase field to progress step
    if (task.phase) {
      phase.value = task.phase
    } else if (task.index_status === 'loading') {
      phase.value = 'loading_index'
    }
    if (task.status === 'done') {
      clearInterval(pollTimer.value)
      status.value = 'done'
      phase.value = 'done'
      result.value = task.result
      meta.value = task.times
    } else if (task.status === 'error') {
      clearInterval(pollTimer.value)
      status.value = 'error'
      phase.value = 'error'
      errorMsg.value = task.error || 'Search error'
    }
  } catch {}
}

function handleCancel() {
  clearInterval(pollTimer.value)
  status.value = 'idle'
  phase.value = 'pending'
  taskId.value = null
  errorMsg.value = null
}

onMounted(() => {
  loadDatasets()
  gpuStore.fetchQueue()
})
</script>
