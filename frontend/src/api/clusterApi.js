import client from './client'

export async function listWorkers() {
  const resp = await client.get('/admin/cluster/workers')
  return resp.data
}

export async function setWorkerStatus(nodeId, status) {
  const resp = await client.post(`/admin/cluster/workers/${encodeURIComponent(nodeId)}/status`, { status })
  return resp.data
}

export async function setWorkerHidden(nodeId, hidden) {
  const resp = await client.post(`/admin/cluster/workers/${encodeURIComponent(nodeId)}/hidden`, { hidden })
  return resp.data
}
