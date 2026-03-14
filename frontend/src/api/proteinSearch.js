import client from './client'

export async function submitSearch(sequence, topK, pooling) {
  const resp = await client.post('/query/submit', { sequence, top_k: topK, pooling })
  return resp.data.task_id
}

export async function getResult(taskId) {
  const resp = await client.get(`/query/result/${encodeURIComponent(taskId)}`)
  return resp.data
}

export async function healthCheck() {
  const resp = await client.get('/health')
  return resp.data
}
