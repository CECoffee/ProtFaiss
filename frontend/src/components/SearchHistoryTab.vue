<template>
  <n-space vertical :size="16">
    <n-data-table
      :columns="listColumns"
      :data="tasks"
      :loading="loading"
      :pagination="pagination"
      :row-props="rowProps"
      size="small"
      striped
      remote
      :empty-text="t('search.history.empty')"
      @update:page="handlePageChange"
    />

    <n-drawer v-model:show="drawerVisible" :width="720" placement="right">
      <n-drawer-content :title="t('search.history.detail.title')" closable>
        <template v-if="detail">
          <n-descriptions :column="2" size="small" style="margin-bottom: 16px">
            <n-descriptions-item :label="t('search.history.detail.dataset')">
              {{ detail.dataset_name || '—' }}
            </n-descriptions-item>
            <n-descriptions-item :label="t('search.history.detail.submitted')">
              {{ formatDate(detail.submitted_at) }}
            </n-descriptions-item>
            <n-descriptions-item :label="t('search.history.detail.gpu')">
              {{ detail.gpu_seconds != null ? detail.gpu_seconds.toFixed(2) + 's' : '—' }}
            </n-descriptions-item>
          </n-descriptions>

          <n-alert v-if="detail.legacy" type="info" :title="t('search.history.detail.legacy')" />
          <n-alert v-else-if="!detail.hits?.length" type="default" :title="t('search.history.detail.noHits')" />
          <n-data-table
            v-else
            :columns="hitColumns"
            :data="detail.hits"
            size="small"
            striped
            :pagination="{ pageSize: 20 }"
          />
        </template>
        <n-spin v-else size="large" style="display:flex;justify-content:center;padding:40px" />
      </n-drawer-content>
    </n-drawer>
  </n-space>
</template>

<script setup>
import { ref, computed, onMounted, h } from 'vue'
import { NTag, NEllipsis } from 'naive-ui'
import { getSearchHistory, getSearchHistoryDetail } from '../api/proteinSearch'
import { useI18n } from '../i18n/index.js'

const { t } = useI18n()

const tasks = ref([])
const total = ref(0)
const loading = ref(false)
const currentPage = ref(1)
const pageSize = 20

const drawerVisible = ref(false)
const detail = ref(null)

const pagination = computed(() => ({
  page: currentPage.value,
  pageSize,
  itemCount: total.value,
  showSizePicker: false,
}))

const listColumns = computed(() => [
  {
    title: t('search.history.col.taskId'),
    key: 'search_task_id',
    width: 300,
    ellipsis: { tooltip: true }
  },
  {
    title: t('search.history.col.dataset'),
    key: 'dataset_name',
    width: 100,
    render: (row) => row.dataset_name || '—',
  },
  {
    title: t('search.history.col.submitted'),
    key: 'submitted_at',
    width: 150,
    render: (row) => formatDate(row.submitted_at),
  },
  {
    title: t('search.history.col.hits'),
    key: 'hit_count',
    width: 60,
    render: (row) => h(NTag, { size: 'small', round: true }, { default: () => row.hit_count ?? 0 }),
  },
  {
    title: t('search.history.col.gpuSeconds'),
    key: 'gpu_seconds',
    width: 60,
    render: (row) => row.gpu_seconds != null ? row.gpu_seconds.toFixed(2) + 's' : '—',
  },
])

const hitColumns = computed(() => [
  { title: t('search.history.col.rank'), key: 'rank', width: 60 },
  { title: t('search.history.col.id'), key: 'protein_row_id', width: 90 },
  {
    title: t('search.col.header'),
    key: 'original_header',
    render: (row) => h(NEllipsis, { style: 'max-width: 200px' }, { default: () => row.original_header || '—' }),
  },
  {
    title: t('search.col.sequence'),
    key: 'sequence',
    render: (row) => h(NEllipsis, { style: 'max-width: 160px' }, { default: () => row.sequence || '—' }),
  },
  { title: t('search.history.col.ko'), key: 'ko_number', width: 90 },
  { title: t('search.history.col.ec'), key: 'ec_number', width: 90 },
  {
    title: t('search.history.col.distance'),
    key: 'faiss_distance',
    width: 100,
    render: (row) => h(NTag, { type: 'info', size: 'small', round: true }, { default: () => row.faiss_distance?.toFixed(4) }),
  },
])

function rowProps(row) {
  return {
    style: 'cursor: pointer',
    onClick: () => openDetail(row.search_task_id),
  }
}

async function loadHistory() {
  loading.value = true
  try {
    const offset = (currentPage.value - 1) * pageSize
    const data = await getSearchHistory(pageSize, offset)
    tasks.value = data.tasks || []
    total.value = data.total || 0
  } catch {}
  loading.value = false
}

async function openDetail(taskId) {
  detail.value = null
  drawerVisible.value = true
  try {
    detail.value = await getSearchHistoryDetail(taskId)
  } catch (e) {
    detail.value = { legacy: true, hits: [], dataset_name: null, submitted_at: null, gpu_seconds: null }
  }
}

function handlePageChange(page) {
  currentPage.value = page
  loadHistory()
}

function formatDate(iso) {
  if (!iso) return '—'
  return iso.slice(0, 19).replace('T', ' ')
}

onMounted(loadHistory)
</script>
