<template>
  <h1>Protein FAISS Search</h1>
  <p class="small">FastAPI + Vue 3 — async submit/poll</p>

  <DatasetSwitcher />

  <div v-if="noDatasetError" class="no-dataset-banner">
    <span>No dataset is active. Please activate a dataset before searching.</span>
    <button class="btn-goto-datasets" @click="$emit('goto-datasets')">Go to Manage Datasets</button>
  </div>

  <SequenceInput @submit="handleSubmit" @cancel="handleCancel" />

  <StatusPanel
    v-if="status !== 'idle'"
    :status="status"
    :task-id="taskId"
    :meta="meta"
  />

  <ResultsList
    v-if="status === 'done' && result"
    :results="result"
    :task-id="taskId"
  />

  <DiagnosticLog v-if="logs.length > 0" :logs="logs" />
</template>

<script setup>
import { ref } from 'vue'
import { submitSearch } from '../api/proteinSearch'
import { usePolling } from '../composables/usePolling'
import SequenceInput from '../components/SequenceInput.vue'
import StatusPanel from '../components/StatusPanel.vue'
import ResultsList from '../components/ResultsList.vue'
import DiagnosticLog from '../components/DiagnosticLog.vue'
import DatasetSwitcher from '../components/DatasetSwitcher.vue'

defineEmits(['goto-datasets'])

const { status, taskId, result, meta, logs, startPolling, stopPolling } = usePolling()
const noDatasetError = ref(false)

async function handleSubmit({ sequence, topK, pooling }) {
  noDatasetError.value = false
  try {
    const id = await submitSearch(sequence, topK, pooling)
    startPolling(id)
  } catch (e) {
    if (e.response?.status === 409) {
      noDatasetError.value = true
    } else {
      console.error('Submit failed:', e)
      alert('Submit failed: ' + (e.response?.data?.detail || e.message))
    }
  }
}

function handleCancel() {
  const wasCancelled = stopPolling()
  if (!wasCancelled) alert('No active polling task')
}
</script>

<style scoped>
.no-dataset-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #fef9c3;
  border: 1px solid #fde047;
  border-radius: 6px;
  color: #854d0e;
  font-size: 0.9rem;
  margin-bottom: 16px;
}
.btn-goto-datasets {
  padding: 4px 14px;
  background: #f59e0b;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.85rem;
  white-space: nowrap;
}
.btn-goto-datasets:hover { background: #d97706; }
</style>