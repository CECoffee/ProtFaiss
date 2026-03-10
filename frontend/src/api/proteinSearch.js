import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  headers: { 'Content-Type': 'application/json' },
})

/**
 * Submit a protein sequence search task.
 * @param {string} sequence
 * @param {number} topK
 * @param {string} pooling
 * @returns {Promise<string>} task_id
 */
export async function submitSearch(sequence, topK, pooling) {
  const resp = await api.post('/query/submit', { sequence, top_k: topK, pooling })
  return resp.data.task_id
}

/**
 * Poll the result of a submitted task.
 * @param {string} taskId
 * @returns {Promise<object>} task object { status, result?, error?, times? }
 */
export async function getResult(taskId) {
  const resp = await api.get(`/query/result/${encodeURIComponent(taskId)}`)
  return resp.data
}

/**
 * Check backend health.
 * @returns {Promise<object>}
 */
export async function healthCheck() {
  const resp = await api.get('/health')
  return resp.data
}
