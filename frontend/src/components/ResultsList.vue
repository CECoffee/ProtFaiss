<template>
  <div class="panel" data-testid="results-panel">
    <h3 style="margin-top:0">检索结果</h3>
    <div class="small-muted" style="margin-bottom:8px">
      Task: <code data-testid="results-task-id">{{ taskId }}</code>
    </div>
    <hr />

    <div v-if="!results || results.length === 0" class="small-muted" data-testid="no-results">未返回结果</div>

    <div v-for="(r, idx) in results" :key="r.id" class="item" data-testid="result-item">
      <div style="display:flex; justify-content:space-between; align-items:center">
        <strong>#{{ idx + 1 }} — ID {{ r.id }}</strong>
        <span class="small-muted" data-testid="result-distance">dist: {{ Number(r.faiss_distance).toFixed(4) }}</span>
      </div>
      <div class="small-muted" data-testid="result-annotations">
        KO: {{ r.ko || 'N/A' }} | EC: {{ r.ec || 'N/A' }} | pH: {{ r.ph || 'N/A' }}
      </div>
      <pre class="header">{{ r.header }}</pre>
      <pre class="seq" data-testid="result-sequence">{{ r.sequence || '' }}</pre>
    </div>
  </div>
</template>

<script setup>
defineProps({
  results: { type: Array, default: () => [] },
  taskId: { type: String, default: '' },
})
</script>
