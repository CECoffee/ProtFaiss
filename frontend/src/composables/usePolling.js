import { ref } from 'vue'
import { getResult } from '../api/proteinSearch'

const INITIAL_DELAY = 500      // ms
const MAX_DELAY = 4000         // ms
const BACKOFF_FACTOR = 1.8
const MAX_ATTEMPTS = 100

/**
 * Composable for exponential-backoff polling of a task result.
 *
 * Exposes:
 *   status    - 'idle' | 'pending' | 'done' | 'error' | 'cancelled' | 'timeout'
 *   taskId    - current task ID being polled
 *   result    - result array when done
 *   times     - timing object { total_time, esm_time, faiss_time, db_time }
 *   errorMsg  - error string if status === 'error'
 *   attempt   - current poll attempt count
 *   logs      - array of { time, message } log entries (newest first)
 *   meta      - human-readable status line
 *   startPolling(id) - begin polling for taskId
 *   stopPolling()    - cancel current poll
 */
export function usePolling() {
  const status = ref('idle')
  const taskId = ref(null)
  const result = ref(null)
  const times = ref(null)
  const errorMsg = ref(null)
  const attempt = ref(0)
  const logs = ref([])
  const meta = ref('')

  let aborted = false
  let polling = false

  function log(message) {
    const time = new Date().toLocaleTimeString()
    logs.value.unshift({ time, message })
  }

  function reset() {
    result.value = null
    times.value = null
    errorMsg.value = null
    attempt.value = 0
    meta.value = ''
    logs.value = []
  }

  async function startPolling(id) {
    // If already polling, abort the previous loop first
    if (polling) {
      aborted = true
      await new Promise(r => setTimeout(r, 120))
    }

    aborted = false
    polling = true
    taskId.value = id
    status.value = 'pending'
    reset()

    let delay = INITIAL_DELAY

    while (!aborted && attempt.value < MAX_ATTEMPTS) {
      attempt.value += 1
      try {
        log(`轮询尝试 #${attempt.value} -> /query/result/${id}`)
        const data = await getResult(id)
        log(`轮询返回 status=${data.status}`)

        if (data.status === 'pending') {
          status.value = 'pending'
          meta.value = `任务未完成（第 ${attempt.value} 次轮询），下一次等待 ${delay}ms`
        } else if (data.status === 'done') {
          status.value = 'done'
          result.value = data.result
          times.value = data.times || null
          const t = data.times || {}
          const totalMs = Math.round((t.total_time || 0) * 1000)
          const esmMs = Math.round((t.esm_time || 0) * 1000)
          const faissMs = Math.round((t.faiss_time || 0) * 1000)
          const dbMs = Math.round((t.db_time || 0) * 1000)
          meta.value = `完成 (轮询次数 ${attempt.value}) — 耗时: 总 ${totalMs} ms (ESM ${esmMs} ms | FAISS ${faissMs} ms | DB ${dbMs} ms)`
          polling = false
          return
        } else if (data.status === 'error') {
          status.value = 'error'
          errorMsg.value = data.error || 'unknown'
          meta.value = `后台任务错误: ${errorMsg.value}`
          log('后台任务错误: ' + errorMsg.value)
          polling = false
          return
        } else {
          status.value = data.status || 'unknown'
          meta.value = `状态: ${data.status}`
        }
      } catch (e) {
        // axios throws on 4xx/5xx — check for 404 to stop polling
        if (e.response && (e.response.status === 404 || e.response.status === 403)) {
          status.value = 'error'
          errorMsg.value = `Error ${e.response.status}: ${JSON.stringify(e.response.data)}`
          meta.value = errorMsg.value
          log(`轮询失败: ${errorMsg.value}`)
          polling = false
          return
        }
        log('轮询异常: ' + e)
      }

      // Exponential backoff wait
      await new Promise(r => setTimeout(r, delay))
      delay = Math.min(MAX_DELAY, Math.floor(delay * BACKOFF_FACTOR))
    }

    if (!aborted) {
      status.value = 'timeout'
      meta.value = '轮询达到最大次数或超时，已停止。'
      log('轮询达到最大次数或超时，停止。')
    } else {
      log('轮询被用户取消')
    }
    polling = false
  }

  function stopPolling() {
    if (!polling) return false
    aborted = true
    status.value = 'cancelled'
    meta.value = '已由用户取消轮询'
    log('用户取消轮询')
    return true
  }

  return { status, taskId, result, times, errorMsg, attempt, logs, meta, startPolling, stopPolling, polling: { get value() { return polling } } }
}
