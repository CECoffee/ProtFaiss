import { ref } from 'vue'
import { listDatasets, switchDataset, deleteDataset } from '../api/buildApi'

/**
 * Composable for managing the dataset list and active dataset.
 *
 * Exposes:
 *   datasets          - ref<object[]>
 *   activeDatasetId   - ref<string|null>
 *   loading           - ref<boolean>
 *   error             - ref<string|null>
 *   refresh()         - reload from /datasets
 *   switchTo(id)      - POST /datasets/switch
 *   remove(id)        - DELETE /datasets/{id}
 */
export function useDatasets() {
  const datasets = ref([])
  const activeDatasetId = ref(null)
  const loading = ref(false)
  const error = ref(null)

  async function refresh() {
    loading.value = true
    error.value = null
    try {
      const data = await listDatasets()
      datasets.value = data.datasets
      activeDatasetId.value = data.active_dataset_id
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
    } finally {
      loading.value = false
    }
  }

  async function switchTo(id) {
    loading.value = true
    error.value = null
    try {
      const data = await switchDataset(id)
      activeDatasetId.value = data.active_dataset_id
      return data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function remove(id) {
    loading.value = true
    error.value = null
    try {
      await deleteDataset(id)
      datasets.value = datasets.value.filter(d => d.id !== id)
      if (activeDatasetId.value === id) activeDatasetId.value = null
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  return { datasets, activeDatasetId, loading, error, refresh, switchTo, remove }
}
