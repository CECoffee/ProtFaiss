import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
})

/**
 * Submit a build job.
 * @param {FormData} formData  — contains file, name, algorithm, and optional params
 * @returns {Promise<{dataset_id: string, status: string}>}
 */
export async function submitBuild(formData) {
  const resp = await api.post('/build/submit', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return resp.data
}

/**
 * Poll build status for a dataset.
 * @param {string} datasetId
 * @returns {Promise<object>} dataset registry entry
 */
export async function getBuildStatus(datasetId) {
  const resp = await api.get(`/build/status/${encodeURIComponent(datasetId)}`)
  return resp.data
}

/**
 * List all datasets plus the active dataset ID.
 * @returns {Promise<{datasets: object[], active_dataset_id: string|null}>}
 */
export async function listDatasets() {
  const resp = await api.get('/datasets')
  return resp.data
}

/**
 * Delete a dataset (files + DB table + registry entry).
 * @param {string} datasetId
 * @returns {Promise<{deleted: string}>}
 */
export async function deleteDataset(datasetId) {
  const resp = await api.delete(`/datasets/${encodeURIComponent(datasetId)}`)
  return resp.data
}

/**
 * Switch the active retrieval source to a different dataset.
 * @param {string} datasetId
 * @returns {Promise<{active_dataset_id: string, shards_loaded: number}>}
 */
export async function switchDataset(datasetId) {
  const resp = await api.post('/datasets/switch', { dataset_id: datasetId })
  return resp.data
}
