import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'

export const useGpuStore = defineStore('gpu', () => {
  const queue = ref([])
  const pool = ref({ total_slots: 0, used_slots: 0, available_slots: 0 })
  const loading = ref(false)

  async function fetchQueue() {
    loading.value = true
    try {
      const resp = await client.get('/gpu/queue')
      queue.value = resp.data.tasks || []
      pool.value = resp.data.pool || pool.value
    } catch {}
    loading.value = false
  }

  return { queue, pool, loading, fetchQueue }
})
