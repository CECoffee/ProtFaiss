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

export async function exportDataset(datasetId, includeIndex = true) {
  const resp = await client.post(`/datasets/${encodeURIComponent(datasetId)}/export`, { include_index: includeIndex })
  return resp.data
}

export async function getExportStatus(datasetId) {
  const resp = await client.get(`/datasets/${encodeURIComponent(datasetId)}/export/status`)
  return resp.data
}

export async function downloadExport(datasetId, filename) {
  const resp = await client.get(
    `/datasets/${encodeURIComponent(datasetId)}/export/download`,
    { responseType: 'blob' },
  )
  const url = URL.createObjectURL(resp.data)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || 'export.7z'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export async function importDataset(formData) {
  const resp = await client.post('/datasets/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return resp.data
}

export async function getImportStatus(datasetId) {
  const resp = await client.get(`/datasets/import/${encodeURIComponent(datasetId)}/status`)
  return resp.data
}
