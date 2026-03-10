<template>
  <div class="datasets-view">
    <h2>Manage Datasets</h2>

    <div v-if="activeDatasetId" class="active-banner">
      Active dataset: <strong>{{ activeName }}</strong>
    </div>

    <button class="btn-refresh" @click="refresh" :disabled="loading">Refresh</button>

    <div v-if="error" class="error-msg">{{ error }}</div>

    <table v-if="datasets.length > 0" class="datasets-table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Algorithm</th>
          <th>Status</th>
          <th>Sequences</th>
          <th>Created</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="ds in datasets" :key="ds.id" :class="{ 'row-active': ds.id === activeDatasetId }">
          <td>{{ ds.name }}</td>
          <td><span class="algo-badge">{{ ds.algorithm }}</span></td>
          <td>
            <span class="status-badge" :class="'status-' + ds.status">{{ ds.status }}</span>
            <span v-if="ds.status === 'building'" class="pct-inline">{{ ds.progress_pct }}%</span>
          </td>
          <td>{{ (ds.num_indexed || ds.num_sequences || 0).toLocaleString() }}</td>
          <td>{{ formatDate(ds.created_at) }}</td>
          <td class="actions">
            <button
              class="btn-use"
              :disabled="ds.status !== 'ready' || ds.id === activeDatasetId || loading"
              @click="handleSwitch(ds.id)"
            >
              Use
            </button>
            <button
              class="btn-delete"
              :disabled="loading"
              @click="handleDelete(ds)"
            >
              Delete
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <p v-else-if="!loading" class="empty-hint">No datasets yet. Go to Build Index to create one.</p>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useDatasets } from '../composables/useDatasets'

const { datasets, activeDatasetId, loading, error, refresh, switchTo, remove } = useDatasets()

onMounted(refresh)

const activeName = computed(() => {
  const ds = datasets.value.find(d => d.id === activeDatasetId.value)
  return ds ? ds.name : activeDatasetId.value
})

async function handleSwitch(id) {
  try {
    await switchTo(id)
  } catch {
    // error displayed via error ref
  }
}

async function handleDelete(ds) {
  if (!window.confirm(`Delete dataset "${ds.name}"? This will remove the index files and database table.`)) return
  try {
    await remove(ds.id)
  } catch {
    // error displayed via error ref
  }
}

function formatDate(ts) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString()
}
</script>

<style scoped>
.datasets-view { max-width: 900px; }
.active-banner {
  padding: 10px 16px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  color: #1e40af;
  margin-bottom: 16px;
  font-size: 0.9rem;
}
.active-banner.inactive {
  background: #f8fafc;
  border-color: #e2e8f0;
  color: #64748b;
}
.btn-refresh {
  margin-bottom: 16px;
  padding: 6px 16px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  cursor: pointer;
  background: white;
}
.btn-refresh:hover { background: #f1f5f9; }
.error-msg { color: #dc2626; margin-bottom: 12px; }
.datasets-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
.datasets-table th {
  text-align: left;
  padding: 10px 12px;
  background: #f8fafc;
  border-bottom: 2px solid #e2e8f0;
  font-weight: 600;
  color: #475569;
}
.datasets-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #e2e8f0;
  vertical-align: middle;
}
.row-active td { background: #eff6ff; }
.algo-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 12px;
  background: #e2e8f0;
  font-size: 0.8rem;
  font-weight: 600;
}
.status-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 0.8rem;
  font-weight: 600;
}
.status-ready { background: #dcfce7; color: #166534; }
.status-building { background: #fef9c3; color: #854d0e; }
.status-error { background: #fee2e2; color: #991b1b; }
.pct-inline { margin-left: 6px; font-size: 0.8rem; color: #64748b; }
.actions { display: flex; gap: 8px; }
.btn-use {
  padding: 4px 12px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.85rem;
}
.btn-use:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-use:hover:not(:disabled) { background: #2563eb; }
.btn-delete {
  padding: 4px 12px;
  background: white;
  color: #dc2626;
  border: 1px solid #fca5a5;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.85rem;
}
.btn-delete:hover:not(:disabled) { background: #fee2e2; }
.empty-hint { color: #94a3b8; margin-top: 24px; }
</style>
