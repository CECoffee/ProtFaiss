<template>
  <h1>Protein FAISS 检索 — 异步提交 (submit → poll)</h1>
  <p class="small">前后端分离版 · FastAPI + Vue 3</p>

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
import { submitSearch } from './api/proteinSearch'
import { usePolling } from './composables/usePolling'
import SequenceInput from './components/SequenceInput.vue'
import StatusPanel from './components/StatusPanel.vue'
import ResultsList from './components/ResultsList.vue'
import DiagnosticLog from './components/DiagnosticLog.vue'

const { status, taskId, result, meta, logs, startPolling, stopPolling } = usePolling()

async function handleSubmit({ sequence, topK, pooling }) {
  try {
    const id = await submitSearch(sequence, topK, pooling)
    startPolling(id)
  } catch (e) {
    console.error('Submit failed:', e)
    alert('提交失败: ' + (e.response?.data?.detail || e.message))
  }
}

function handleCancel() {
  const wasCancelled = stopPolling()
  if (!wasCancelled) alert('当前没有正在轮询的任务')
}
</script>
