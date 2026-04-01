import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import client from '../api/client'
import { getGpuHistory, getAdminGpuHistory } from '../api/adminApi'
import { useAuthStore } from './auth'

export const useGpuStore = defineStore('gpu', () => {
  const queue = ref([])
  const pool = ref({ total_slots: 0, used_slots: 0, available_slots: 0 })
  const loading = ref(false)

  const historyTasks = ref([])
  const historyTotal = ref(0)
  const historyHasMore = ref(false)
  const historyLoading = ref(false)
  const historyFilters = ref({
    limit: 50,
    offset: 0,
    status_filter: null,
    task_type_filter: null,
    task_id_filter: null,
    username_filter: null,
    start_date: null,
    end_date: null
  })

  const gpuAvailable = computed(() => pool.value.total_slots > 0)

  async function fetchQueue() {
    loading.value = true
    try {
      const resp = await client.get('/gpu/queue')
      queue.value = resp.data.tasks || []
      pool.value = resp.data.pool || pool.value
    } catch {}
    loading.value = false
  }

  async function fetchHistory(filters = {}) {
    historyLoading.value = true
    try {
      const authStore = useAuthStore()
      const isAdmin = authStore.user?.role === 'admin'

      const params = { ...historyFilters.value, ...filters }
      if (params.status_filter && Array.isArray(params.status_filter)) {
        params.status_filter = params.status_filter.join(',')
      }

      const result = isAdmin
        ? await getAdminGpuHistory(params)
        : await getGpuHistory(params)

      historyTasks.value = result.tasks || []
      historyTotal.value = result.total || 0
      historyHasMore.value = result.has_more || false
    } catch (error) {
      historyTasks.value = []
      historyTotal.value = 0
      historyHasMore.value = false
    }
    historyLoading.value = false
  }

  function setHistoryFilters(filters) {
    historyFilters.value = { ...historyFilters.value, ...filters }
  }

  function resetHistoryFilters() {
    historyFilters.value = {
      limit: 50,
      offset: 0,
      status_filter: null,
      task_type_filter: null,
      task_id_filter: null,
      username_filter: null,
      start_date: null,
      end_date: null
    }
  }

  return {
    queue, pool, loading, gpuAvailable, fetchQueue,
    historyTasks, historyTotal, historyHasMore, historyLoading, historyFilters,
    fetchHistory, setHistoryFilters, resetHistoryFilters
  }
})
