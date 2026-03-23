<template>
  <div>
    <n-space vertical :size="20">
      <n-card :title="t('build.title')">
        <n-text depth="3">{{ t('build.subtitle') }}</n-text>
      </n-card>

      <!-- Build form -->
      <n-card v-if="buildStatus === 'idle'">
        <n-alert v-if="!gpuStore.gpuAvailable" type="error" :title="t('build.noGpu')" style="margin-bottom: 16px" />
        <n-form :model="form" label-placement="top">
          <n-form-item :label="t('build.fileLabel')">
            <n-upload :max="1" accept=".fasta,.fa,.faa" :default-upload="false" @change="onFileChange">
              <n-upload-dragger>
                <div style="padding: 20px 0">
                  <n-icon size="40" depth="3"><CloudUploadOutline /></n-icon>
                  <n-text style="display: block; margin-top: 8px">{{ t('build.fileDrag') }}</n-text>
                  <n-text depth="3" style="font-size: 0.8rem">
                    {{ selectedFile ? selectedFile.name + ' (' + formatSize(selectedFile.size) + ')' : t('build.fileSupports') }}
                  </n-text>
                </div>
              </n-upload-dragger>
            </n-upload>
          </n-form-item>

          <n-form-item :label="t('build.nameLabel')">
            <n-input v-model:value="form.name" :placeholder="t('build.namePlaceholder')" />
          </n-form-item>

          <n-form-item :label="t('build.algoLabel')">
            <n-radio-group v-model:value="form.algorithm">
              <n-space vertical>
                <n-radio value="flat">
                  <n-space align="center">{{ t('build.algoFlat') }}<n-tag size="small" type="info">Exact</n-tag></n-space>
                </n-radio>
                <n-radio value="ivfpq">
                  <n-space align="center">{{ t('build.algoIvfpq') }}<n-tag size="small" type="success">Fast</n-tag></n-space>
                </n-radio>
                <n-radio value="hnsw">
                  <n-space align="center">{{ t('build.algoHnsw') }}<n-tag size="small" type="warning">CPU</n-tag></n-space>
                </n-radio>
              </n-space>
            </n-radio-group>
          </n-form-item>

          <n-collapse v-if="form.algorithm !== 'flat'">
            <n-collapse-item :title="t('build.advanced')" name="params">
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

          <n-button type="primary" :disabled="!selectedFile || !form.name || !gpuStore.gpuAvailable" style="margin-top: 16px" @click="handleSubmit">
            {{ t('build.btnStart') }}
          </n-button>
        </n-form>
      </n-card>

      <!-- Progress panel -->
      <n-card v-if="buildStatus !== 'idle'" :title="t('build.progressTitle')">
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

          <n-text depth="3" style="font-size: 0.85rem">{{ t('build.step', { step: progressStep }) }}</n-text>

          <n-alert v-if="buildStatus === 'ready'" type="success" :title="t('build.complete')" />
          <n-alert v-if="buildStatus === 'error'" type="error" :title="t('build.failed', { msg: errorMsg })" />

          <n-button v-if="buildStatus === 'ready' || buildStatus === 'error'" @click="resetForm">
            {{ t('build.btnAnother') }}
          </n-button>
        </n-space>
      </n-card>
    </n-space>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { CloudUploadOutline, CheckmarkCircleOutline, CloseCircleOutline } from '@vicons/ionicons5'
import { submitBuild, getBuildStatus } from '../api/buildApi'
import { useI18n } from '../i18n/index.js'
import { useGpuStore } from '../stores/gpu'

const { t } = useI18n()
const gpuStore = useGpuStore()

onMounted(() => gpuStore.fetchQueue())

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
  idle: t('build.status.idle'),
  building: t('build.status.building'),
  ready: t('build.status.ready'),
  error: t('build.status.error'),
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
