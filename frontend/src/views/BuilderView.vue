<template>
  <div class="builder-view">
    <h2>Build Index from FASTA</h2>
    <p class="hint">Upload a FASTA file to import sequences into PostgreSQL and build a FAISS index.</p>

    <form v-if="buildStatus === 'idle'" @submit.prevent="handleSubmit" class="build-form">
      <!-- File upload -->
      <div class="form-group">
        <label>FASTA file (.fasta / .fa / .faa)</label>
        <div
          class="dropzone"
          :class="{ 'drag-over': dragging }"
          @dragover.prevent="dragging = true"
          @dragleave="dragging = false"
          @drop.prevent="onDrop"
          @click="$refs.fileInput.click()"
        >
          <span v-if="!selectedFile">Click or drag a FASTA file here</span>
          <span v-else class="file-chosen">{{ selectedFile.name }} ({{ formatSize(selectedFile.size) }})</span>
        </div>
        <input
          ref="fileInput"
          type="file"
          accept=".fasta,.fa,.faa"
          style="display: none"
          @change="onFileChange"
        />
      </div>

      <!-- Dataset name -->
      <div class="form-group">
        <label for="dataset-name">Dataset name</label>
        <input
          id="dataset-name"
          v-model="datasetName"
          type="text"
          placeholder="e.g. KEGG test set"
          required
        />
      </div>

      <!-- Algorithm selection -->
      <div class="form-group">
        <label>Index algorithm</label>
        <div class="radio-group">
          <label><input type="radio" v-model="algorithm" value="flat" /> Flat (exact, L2)</label>
          <label><input type="radio" v-model="algorithm" value="ivfpq" /> IVF-PQ (approximate, GPU-accelerated)</label>
          <label><input type="radio" v-model="algorithm" value="hnsw" /> HNSW (approximate, CPU)</label>
        </div>
      </div>

      <!-- Advanced params (collapsible) -->
      <details v-if="algorithm !== 'flat'" class="advanced-params">
        <summary>Advanced parameters</summary>
        <div v-if="algorithm === 'ivfpq'" class="param-grid">
          <label>nlist (IVF centroids)</label>
          <input v-model.number="params.nlist" type="number" min="16" max="65536" />
          <label>PQ sub-quantizers (m)</label>
          <input v-model.number="params.pq_m" type="number" min="8" max="256" />
          <label>Bits per sub-space</label>
          <input v-model.number="params.nbits" type="number" min="4" max="12" />
        </div>
        <div v-if="algorithm === 'hnsw'" class="param-grid">
          <label>HNSW M</label>
          <input v-model.number="params.hnsw_m" type="number" min="4" max="128" />
          <label>ef_construction</label>
          <input v-model.number="params.ef_construction" type="number" min="40" max="2000" />
        </div>
      </details>

      <button type="submit" :disabled="!selectedFile || !datasetName" class="btn-primary">
        Start Build
      </button>
    </form>

    <!-- Progress panel -->
    <div v-if="buildStatus !== 'idle'" class="progress-panel">
      <div class="progress-header">
        <span>{{ statusLabel }}</span>
        <span class="pct-badge">{{ progressPct }}%</span>
      </div>
      <progress :value="progressPct" max="100" class="progress-bar"></progress>
      <p class="step-label">Step: {{ progressStep }}</p>

      <div v-if="buildStatus === 'ready'" class="success-banner">
        Build complete! Dataset is ready.
        <button class="btn-link" @click="$emit('goto-datasets')">View in Manage Datasets</button>
      </div>

      <div v-if="buildStatus === 'error'" class="error-banner">
        Build failed: {{ errorMsg }}
      </div>

      <button
        v-if="buildStatus === 'ready' || buildStatus === 'error'"
        class="btn-secondary"
        @click="resetForm"
      >
        Build another
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { submitBuild } from '../api/buildApi'
import { useBuildPolling } from '../composables/useBuildPolling'

defineEmits(['goto-datasets'])

const { status: buildStatus, progressPct, progressStep, errorMsg, startPolling } = useBuildPolling()

const fileInput = ref(null)
const selectedFile = ref(null)
const dragging = ref(false)
const datasetName = ref('')
const algorithm = ref('flat')
const params = ref({
  nlist: 256,
  pq_m: 64,
  nbits: 8,
  hnsw_m: 32,
  ef_construction: 200,
})

const statusLabel = computed(() => {
  const map = {
    idle: 'Idle',
    building: 'Building...',
    ready: 'Done',
    error: 'Error',
    cancelled: 'Cancelled',
    timeout: 'Timeout',
  }
  return map[buildStatus.value] || buildStatus.value
})

function onFileChange(e) {
  selectedFile.value = e.target.files[0] || null
}

function onDrop(e) {
  dragging.value = false
  const f = e.dataTransfer.files[0]
  if (f) selectedFile.value = f
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

async function handleSubmit() {
  const fd = new FormData()
  fd.append('file', selectedFile.value)
  fd.append('name', datasetName.value)
  fd.append('algorithm', algorithm.value)
  if (algorithm.value === 'ivfpq') {
    fd.append('nlist', params.value.nlist)
    fd.append('pq_m', params.value.pq_m)
    fd.append('nbits', params.value.nbits)
  } else if (algorithm.value === 'hnsw') {
    fd.append('hnsw_m', params.value.hnsw_m)
    fd.append('ef_construction', params.value.ef_construction)
  }

  try {
    const { dataset_id } = await submitBuild(fd)
    await startPolling(dataset_id)
  } catch (e) {
    alert('Submit failed: ' + (e.response?.data?.detail || e.message))
  }
}

function resetForm() {
  selectedFile.value = null
  datasetName.value = ''
  buildStatus.value = 'idle'
}
</script>

<style scoped>
.builder-view { max-width: 640px; }
.hint { color: #64748b; margin-bottom: 20px; }
.build-form { display: flex; flex-direction: column; gap: 18px; }
.form-group { display: flex; flex-direction: column; gap: 6px; }
.form-group label { font-weight: 600; font-size: 0.9rem; }
.form-group input[type="text"] {
  padding: 8px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 0.95rem;
}
.dropzone {
  border: 2px dashed #94a3b8;
  border-radius: 8px;
  padding: 32px;
  text-align: center;
  cursor: pointer;
  color: #64748b;
  transition: border-color 0.15s, background 0.15s;
}
.dropzone:hover, .dropzone.drag-over {
  border-color: #3b82f6;
  background: #eff6ff;
}
.file-chosen { color: #1e40af; font-weight: 600; }
.radio-group { display: flex; flex-direction: column; gap: 8px; }
.radio-group label { font-weight: normal; cursor: pointer; }
.advanced-params { margin-top: 4px; }
.advanced-params summary { cursor: pointer; color: #475569; font-size: 0.9rem; }
.param-grid {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 8px;
  align-items: center;
  margin-top: 10px;
}
.param-grid input {
  padding: 6px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
}
.btn-primary {
  padding: 10px 24px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 0.95rem;
  cursor: pointer;
  align-self: flex-start;
}
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary:hover:not(:disabled) { background: #2563eb; }
.btn-secondary {
  margin-top: 12px;
  padding: 8px 18px;
  background: white;
  border: 1px solid #94a3b8;
  border-radius: 6px;
  cursor: pointer;
}
.btn-link {
  background: none;
  border: none;
  color: #3b82f6;
  cursor: pointer;
  text-decoration: underline;
  font-size: inherit;
  padding: 0 4px;
}
.progress-panel { margin-top: 24px; }
.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-weight: 600;
}
.pct-badge {
  background: #e2e8f0;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 0.85rem;
}
.progress-bar { width: 100%; height: 12px; border-radius: 6px; }
.step-label { color: #64748b; font-size: 0.85rem; margin-top: 6px; }
.success-banner {
  margin-top: 16px;
  padding: 12px 16px;
  background: #f0fdf4;
  border: 1px solid #86efac;
  border-radius: 6px;
  color: #166534;
}
.error-banner {
  margin-top: 16px;
  padding: 12px 16px;
  background: #fef2f2;
  border: 1px solid #fca5a5;
  border-radius: 6px;
  color: #991b1b;
}
</style>
