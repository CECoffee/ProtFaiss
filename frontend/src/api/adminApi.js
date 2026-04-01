import client from './client'

export async function listUsers(limit = 50, offset = 0) {
  const resp = await client.get('/admin/users', { params: { limit, offset } })
  return resp.data
}

export async function updateUser(userId, patch) {
  const resp = await client.patch(`/admin/users/${userId}`, patch)
  return resp.data
}

export async function deleteUser(userId) {
  const resp = await client.delete(`/admin/users/${userId}`)
  return resp.data
}

export async function getStats() {
  const resp = await client.get('/admin/stats')
  return resp.data
}

export async function getGpuQueue() {
  const resp = await client.get('/admin/gpu/queue')
  return resp.data
}

export async function cancelTask(taskId) {
  const resp = await client.post(`/admin/gpu/tasks/${taskId}/cancel`)
  return resp.data
}

export async function reloadConfig() {
  const resp = await client.post('/admin/reload-config')
  return resp.data
}

export async function getGpuStatus() {
  const resp = await client.get('/gpu/status')
  return resp.data
}

export async function getGpuHistory(params = {}) {
  const resp = await client.get('/gpu/history', { params })
  return resp.data
}

export async function getAdminGpuHistory(params = {}) {
  const resp = await client.get('/admin/gpu/history', { params })
  return resp.data
}
