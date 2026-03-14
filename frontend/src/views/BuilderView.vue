<template>
  <div>
    <n-space vertical :size="20">
      <n-card title="Build Index from FASTA">
        <n-text depth="3">Upload a FASTA file to import sequences into PostgreSQL and build a FAISS index.</n-text>
      </n-card>

      <!-- Build form -->
      <n-card v-if="buildStatus === 'idle'">
        <n-form :model="form" label-placement="top">
          <!-- File upload -->
          <n-form-item label="FASTA File (.fasta / .fa / .faa)">
            <n-upload
              :max="1"
              accept=".fasta,.fa,.faa"
              :default-upload="false"
              @change="onFileChange"
            >
              <n-upload-dragger>
                <div style="padding: 20px 0">
                  <n-icon size="40" depth="3"><CloudUploadOutline /></n-icon>
                  <n-text style="display: block; margin-top: 8px">
                    Click or drag a FASTA file here
                  </n-text>
                  <n-text depth="3" style="font-size: 0.8rem">
                    {{ selectedFile ? selectedFile.name + ' (' + formatSize(selectedFile.size) + ')' : 'Supports .fasta, .fa, .faa' }}
                  </n-text>
                </div>
              </n-upload-dragger>
            </n-upload>
          </n-form-item>

          <!-- Dataset name -->
          <n-form-item label="Dataset Name">
            <n-input v-model:value="form.name" placeholder="e.g. KEGG test set" />
          </n-form-item>

          <!-- Algorithm -->
          <n-form-item label="Index Algorithm">
            <n-radio-group v-model:value="form.algorithm">
              <n-space vertical>
                <n-radio value="flat">
                  <n-space align="center">
                    Flat (exact, L2)
                    <n-tag size="small" type="info">Exact</n-tag>
                  </n-space>
                </n-radio>
                <n-radio value="ivfpq">
                  <n-space align="center">
                    IVF-PQ (approximate, GPU-accelerated)
                    <n-tag size="small" type="success">Fast</n-tag>
                  </n-space>
                </n-radio>
                <n-radio value="hnsw">
                  <n-space align="center">
                    HNSW (approximate, CPU)
                    <n-tag size="small" type="warning">CPU</n-tag>
                  </n-space>
                </n-radio>
              </n-space>
            </n-radio-group>
          </n-form-item>

          <!-- Advanced params -->
          <n-collapse v-if="form.algorithm !== 'flat'">
            <n-collapse-item title="Advanced Parameters" name="params">
              <n-grid v-if="form.algorithm === 'ivfpq'" :cols="3" :x-gap="16">
                <n-gi>
                  <n-form-item label="nlist (IVF centroids)">
                    <n-input-number v-model:value="form.nlist" :min="16" :max="65536" />
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="PQ sub-quantizers (m)">
                    <n-input-number v-model:value="form.pq_m" :min="8" :max="256" />
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Bits per sub-space">
                    <n-input-number v-model:value="form.nbits" :min="4" :max="12" />
                  </n-form-item>
                </n-gi>
              </n-grid>
              <n-grid v-if="form.algorithm === 'hnsw'" :cols="2" :x-gap="16">
                <n-gi>
                  <n-form-item label="HNSW M">
                    <n-input-number v-model:value="form.hnsw_m" :min="4" :max="128" />
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="ef_construction">
                    <n-input-number v-model:value="form.ef_construction" :min="40" :max="2000" />
                  </n-form-item>
                </n-gi>
              </n-grid>
            </n-collapse-item>
          </n-collapse>

          <n-button
            type="primary"
            :disabled="!selectedFile || !form.name"
            style="margin-top: 16px"
            @click="handleSubmit"
          >
            Start Build
          </n-button>
        </n-form>
      </n-card>

      <!-- Progress panel -->
      <n-card v-if="buildStatus !== 'idle'" title="Build Progress">
        <n-space vertical :size="16">
          <n-space justify="space-between" align="center">
            <n-space align="center">
              <n-spin v-if="buildStatus === 'building'" size="small" />
              <n-icon v-else-if="buildStatus === 'ready'" color="#18a058" size="18"><CheckmarkCircleOutline /></n-icon>
              <n-icon v-else color="#d03050" size="18"><CloseCircleOutline /></n-icon>
              <n-text strong>{{ statusLabel }}</n-text>
            </n-space>
            <n-tag round>{{ progressPct }}%</n-tag>
          </n-space>

          <n-progress
            type="line"
            :percentage="progressPct"
            :status="progressStatus"
            :height="12"
            :border-radius="6"
            indicator-placement="inside"
          />

          <n-text depth="3" style="font-size: 0.85rem">Step: {{ progressStep }}</n-text>

          <n-alert v-if="buildStatus === 'ready'" type="success" title="Build complete! Dataset is ready." />
          <n-alert v-if="buildStatus === 'error'" type="error" :title="'Build failed: ' + errorMsg" />

          <n-button v-if="buildStatus === 'ready' || buildStatus === 'error'" @click="resetForm">
            Build another
          </n-button>
        </n-space>
      </n-card>
    </n-space>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { CloudUploadOutline, CheckmarkCircleOutline, CloseCircleOutline } from '@vicons/ionicons5'
import { submitBuild, getBuildStatus } from '../api/buildApi'

const selectedFile = ref(null)
const buildStatus = ref('idle')
const progressPct = ref(0)
const progressStep = ref('')
const errorMsg = ref('')
let pollTimer = null

const form = ref({
  name: '',
  algorithm: 'flat',
  nlist: 256,
  pq_m: 64,
  nbits: 8,
  hnsw_m: 32,
  ef_construction: 200,
})

const statusLabel = computed(() => ({
  idle: 'Idle', building: 'Building...', ready: 'Done', error: 'Error',
}[buildStatus.value] || buildStatus.value))

const progressStatus = computed(() => ({
  building: 'default', ready: 'success', error: 'error',
}[buildStatus.value] || 'default'))

function onFileChange({ fileList }) {
  selectedFile.value = fileList[0]?.file || null
}

function formatSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

async function handleSubmit() {
  const fd = new FormData()
  fd.append('file', selectedFile.value)
  fd.append('name', form.value.name)
  fd.append('algorithm', form.value.algorithm)
  if (form.value.algorithm === 'ivfpq') {
    fd.append('nlist', form.value.nlist)
    fd.append('pq_m', form.value.pq_m)
    fd.append('nbits', form.value.nbits)
  } else if (form.value.algorithm === 'hnsw') {
    fd.append('hnsw_m', form.value.hnsw_m)
    fd.append('ef_construction', form.value.ef_construction)
  }
  try {
    const { dataset_id } = await submitBuild(fd)
    buildStatus.value = 'building'
    pollTimer = setInterval(() => pollBuild(dataset_id), 2000)
  } catch (e) {
    window.$message?.error(e.response?.data?.detail || 'Submit failed')
  }
}

async function pollBuild(id) {
  try {
    const entry = await getBuildStatus(id)
    progressPct.value = Math.round(entry.progress_pct || 0)
    progressStep.value = entry.progress_step || ''
    if (entry.status === 'ready') {
      clearInterval(pollTimer)
      buildStatus.value = 'ready'
    } else if (entry.status === 'error') {
      clearInterval(pollTimer)
      buildStatus.value = 'error'
      errorMsg.value = entry.error_msg || 'Unknown error'
    }
  } catch {}
}

function resetForm() {
  clearInterval(pollTimer)
  buildStatus.value = 'idle'
  selectedFile.value = null
  progressPct.value = 0
  progressStep.value = ''
  errorMsg.value = ''
  form.value.name = ''
}
</script>
