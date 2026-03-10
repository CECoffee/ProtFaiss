/**
 * Shared mock data and API route helpers for E2E tests.
 * All tests mock the backend API via page.route() since
 * the real backend requires GPU resources.
 */

export const SAMPLE_SEQUENCE = '>Query_1\nMSNYFVSGISSGIRSVGKSSTAIRRIAR'
export const MOCK_TASK_ID = 'test-task-abc123'

export const MOCK_RESULTS = [
  {
    id: 1001,
    faiss_distance: 0.1234,
    ko: 'K00001',
    ec: '1.1.1.1',
    ph: '7.0',
    header: '>sp|P12345|PROT_HUMAN Test protein 1',
    sequence: 'MSNYFVSGISSGIRSV',
  },
  {
    id: 1002,
    faiss_distance: 0.2567,
    ko: 'K00002',
    ec: '2.3.1.4',
    ph: '6.5',
    header: '>sp|P67890|PROT2_HUMAN Test protein 2',
    sequence: 'ACDEFGHIKLMNPQRST',
  },
]

export const MOCK_TIMES = {
  total_time: 1.234,
  esm_time: 0.800,
  faiss_time: 0.300,
  db_time: 0.134,
}

/**
 * Mock a successful submit → single-poll-done flow.
 */
export async function mockSuccessFlow(page, { taskId = MOCK_TASK_ID, results = MOCK_RESULTS } = {}) {
  await page.route('/query/submit', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ task_id: taskId }),
    })
  })

  await page.route(`/query/result/${taskId}`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'done', result: results, times: MOCK_TIMES }),
    })
  })
}

/**
 * Mock submit success but poll returns 'pending' N times then 'done'.
 */
export async function mockPendingThenDone(page, { pendingCount = 2, taskId = MOCK_TASK_ID } = {}) {
  await page.route('/query/submit', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ task_id: taskId }),
    })
  })

  let pollCount = 0
  await page.route(`/query/result/${taskId}`, async route => {
    pollCount += 1
    if (pollCount <= pendingCount) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'pending' }),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'done', result: MOCK_RESULTS, times: MOCK_TIMES }),
      })
    }
  })
}

/**
 * Mock submit success but poll returns backend error status.
 */
export async function mockBackendError(page, { taskId = MOCK_TASK_ID, errorMsg = 'GPU OOM' } = {}) {
  await page.route('/query/submit', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ task_id: taskId }),
    })
  })

  await page.route(`/query/result/${taskId}`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'error', error: errorMsg }),
    })
  })
}

/**
 * Mock submit HTTP failure (e.g. 500).
 */
export async function mockSubmitFailure(page, { status = 500, detail = 'Internal Server Error' } = {}) {
  await page.route('/query/submit', async route => {
    await route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify({ detail }),
    })
  })
}

/**
 * Mock poll returning 404 (task not found).
 */
export async function mockPoll404(page, { taskId = MOCK_TASK_ID } = {}) {
  await page.route('/query/submit', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ task_id: taskId }),
    })
  })

  await page.route(`/query/result/${taskId}`, async route => {
    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'task not found' }),
    })
  })
}
