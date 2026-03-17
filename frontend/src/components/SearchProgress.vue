<template>
  <n-card size="small">
    <n-steps :current="currentStep" :status="stepStatus" size="small">
      <n-step :title="t('progress.queued')" />
      <n-step :title="t('progress.model')" />
      <n-step :title="t('progress.index')" />
      <n-step :title="t('progress.encoding')" />
      <n-step :title="t('progress.searching')" />
      <n-step :title="t('progress.done')" />
    </n-steps>

    <div v-if="phase === 'loading_index'" style="margin-top: 10px">
      <n-text depth="3" style="font-size: 0.8rem">{{ t('progress.loadingIndex') }}</n-text>
    </div>

    <div v-if="times && currentStep === 6" style="margin-top: 10px">
      <n-text depth="3" style="font-size: 0.8rem">{{ timingText }}</n-text>
    </div>

    <div v-if="error" style="margin-top: 10px">
      <n-text type="error" style="font-size: 0.8rem">{{ error }}</n-text>
    </div>
  </n-card>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from '../i18n/index.js'

const { t } = useI18n()

const props = defineProps({
  phase: { type: String, default: 'pending' },
  times: { type: Object, default: null },
  error: { type: String, default: null },
})

// phase values from backend: pending, loading_model, loading_index, encoding, searching, done, error
const PHASE_STEP = {
  pending: 1,
  loading_model: 2,
  loading_index: 3,
  encoding: 4,
  searching: 5,
  done: 6,
}

const currentStep = computed(() => PHASE_STEP[props.phase] ?? 1)

const stepStatus = computed(() => {
  if (props.error) return 'error'
  if (props.phase === 'done') return 'finish'
  return 'process'
})

const timingText = computed(() => {
  if (!props.times) return ''
  const esm = props.times.esm_time?.toFixed(2) ?? '0'
  const faiss = props.times.faiss_time?.toFixed(2) ?? '0'
  const db = props.times.db_time?.toFixed(2) ?? '0'
  const load = props.times.index_load_time
  if (load > 0) {
    return t('progress.timings', { esm, load: load.toFixed(2), faiss, db })
  }
  return t('progress.timingsNoLoad', { esm, faiss, db })
})
</script>
