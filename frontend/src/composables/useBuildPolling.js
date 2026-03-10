import { ref } from 'vue'
import { getBuildStatus } from '../api/buildApi'

const INITIAL_DELAY = 2000    // ms — builds are long-running
const MAX_DELAY = 10000       // ms
const BACKOFF_FACTOR = 1.5
const MAX_ATTEMPTS = 1800     // 30 min at max delay

/**
 * Composable for polling a dataset build job.
 *
 * Exposes:
 *   status        - 'idle' | 'building' | 'ready' | 'error' | 'cancelled' | 'timeout'
 *   datasetId     - dataset ID being polled
 *   progressPct   - 0–100
 *   progressStep  - 'idle' | 'importing' | 'building' | 'done' | 'error'
 *   errorMsg      - error string if status === 'error'
 *   startPolling(id) - begin polling for datasetId
 *   stopPolling()    - cancel current poll
 */
export function useBuildPolling() {
  const status = ref('idle')
  const datasetId = ref(null)
  const progressPct = ref(0)
  const progressStep = ref('idle')
  const errorMsg = ref(null)

  let aborted = false
  let polling = false

  function reset() {
    progressPct.value = 0
    progressStep.value = 'idle'
    errorMsg.value = null
  }

  async function startPolling(id) {
    if (polling) {
      aborted = true
      await new Promise(r => setTimeout(r, 150))
    }

    aborted = false
    polling = true
    datasetId.value = id
    status.value = 'building'
    reset()

    let delay = INITIAL_DELAY
    let attempt = 0

    while (!aborted && attempt < MAX_ATTEMPTS) {
      attempt++
      try {
        const data = await getBuildStatus(id)
        progressPct.value = data.progress_pct ?? 0
        progressStep.value = data.progress_step ?? 'building'

        if (data.status === 'ready') {
          status.value = 'ready'
          polling = false
          return data
        } else if (data.status === 'error') {
          status.value = 'error'
          errorMsg.value = data.error_msg || 'Unknown error'
          polling = false
          return data
        }
        // still 'building' — continue polling
      } catch (e) {
        if (e.response && (e.response.status === 404 || e.response.status === 403)) {
          status.value = 'error'
          errorMsg.value = `HTTP ${e.response.status}`
          polling = false
          return null
        }
        // transient network error — keep polling
      }

      await new Promise(r => setTimeout(r, delay))
      delay = Math.min(MAX_DELAY, Math.floor(delay * BACKOFF_FACTOR))
    }

    if (!aborted) {
      status.value = 'timeout'
    } else {
      status.value = 'cancelled'
    }
    polling = false
    return null
  }

  function stopPolling() {
    if (!polling) return false
    aborted = true
    status.value = 'cancelled'
    return true
  }

  return {
    status,
    datasetId,
    progressPct,
    progressStep,
    errorMsg,
    startPolling,
    stopPolling,
  }
}
