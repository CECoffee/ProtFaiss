import client from './client'

export async function submitBuild(formData) {
  const resp = await client.post('/build/submit', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return resp.data
}

export async function getBuildStatus(datasetId) {
  const resp = await client.get(`/build/status/${encodeURIComponent(datasetId)}`)
  return resp.data
}

export async function listDatasets() {
  const resp = await client.get('/datasets')
  return resp.data
}

export async function deleteDataset(datasetId) {
  const resp = await client.delete(`/datasets/${encodeURIComponent(datasetId)}`)
  return resp.data
}

export async function switchDataset(datasetId) {
  const resp = await client.post('/datasets/switch', { dataset_id: datasetId })
  return resp.data
}

export async function setDatasetVisibility(datasetId, visibility) {
  const resp = await client.patch(`/datasets/${encodeURIComponent(datasetId)}/visibility`, { visibility })
  return resp.data
}
