<template>
  <div class="dataset-switcher" v-if="readyDatasets.length > 0">
    <label for="dataset-select">Active dataset:</label>
    <select
      id="dataset-select"
      :value="activeDatasetId"
      @change="onSwitch($event.target.value)"
      :disabled="loading"
    >
      <option
        v-for="ds in readyDatasets"
        :key="ds.id"
        :value="ds.id"
      >
        {{ ds.name }} ({{ ds.algorithm }}, {{ ds.num_indexed.toLocaleString() }} seqs)
      </option>
    </select>
    <span v-if="error" class="switcher-error">{{ error }}</span>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useDatasets } from '../composables/useDatasets'

const { datasets, activeDatasetId, loading, error, refresh, switchTo } = useDatasets()

const readyDatasets = computed(() => datasets.value.filter(d => d.status === 'ready'))

onMounted(refresh)

async function onSwitch(id) {
  if (!id) return
  try {
    await switchTo(id)
  } catch {
    // error is already set in composable
  }
}
</script>

<style scoped>
.dataset-switcher {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  padding: 10px 14px;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 6px;
  font-size: 0.9rem;
}
.dataset-switcher label {
  font-weight: 600;
  white-space: nowrap;
  color: #0369a1;
}
.dataset-switcher select {
  flex: 1;
  padding: 4px 8px;
  border: 1px solid #7dd3fc;
  border-radius: 4px;
  background: white;
}
.switcher-error {
  color: #dc2626;
  font-size: 0.85rem;
}
</style>
