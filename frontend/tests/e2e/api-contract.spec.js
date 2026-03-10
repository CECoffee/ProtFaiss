import { test, expect } from '@playwright/test'
import { SearchPage } from './pages/SearchPage.js'
import { SAMPLE_SEQUENCE, MOCK_TASK_ID } from './fixtures/api.js'

/**
 * API contract tests — verify the frontend sends correctly-shaped
 * HTTP requests to the backend endpoints.
 */
test.describe('API contract', () => {
  let searchPage

  test.beforeEach(async ({ page }) => {
    searchPage = new SearchPage(page)
    await searchPage.goto()
  })

  test('POST /query/submit sends correct JSON body', async ({ page }) => {
    let request = null
    await page.route('/query/submit', async route => {
      request = route.request()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ task_id: MOCK_TASK_ID }),
      })
    })
    await page.route(`/query/result/${MOCK_TASK_ID}`, async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'done', result: [], times: {} }),
      })
    })

    await searchPage.fillSequence(SAMPLE_SEQUENCE)
    await searchPage.clickSubmit()
    await searchPage.waitForStatus('done', { timeout: 10_000 })

    expect(request).not.toBeNull()
    expect(request.method()).toBe('POST')

    const body = JSON.parse(request.postData())
    expect(body).toMatchObject({
      sequence: SAMPLE_SEQUENCE,
      top_k: 5,
      pooling: 'mean',
    })

    const contentType = request.headers()['content-type']
    expect(contentType).toContain('application/json')
  })

  test('GET /query/result/{task_id} uses URL-encoded task ID', async ({ page }) => {
    const specialTaskId = 'task-123_abc'
    const capturedUrls = []

    await page.route('/query/submit', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ task_id: specialTaskId }),
      })
    })
    await page.route(`/query/result/${specialTaskId}`, async route => {
      capturedUrls.push(route.request().url())
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'done', result: [], times: {} }),
      })
    })

    await searchPage.fillSequence(SAMPLE_SEQUENCE)
    await searchPage.clickSubmit()
    await searchPage.waitForStatus('done', { timeout: 10_000 })

    expect(capturedUrls.length).toBeGreaterThan(0)
    expect(capturedUrls[0]).toContain(specialTaskId)
    expect(capturedUrls[0]).toContain('/query/result/')
  })

  test('displays task_id from server response in status panel', async ({ page }) => {
    const uniqueId = 'unique-task-xyz-999'
    await page.route('/query/submit', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ task_id: uniqueId }),
      })
    })
    await page.route(`/query/result/${uniqueId}`, async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'done', result: [], times: {} }),
      })
    })

    await searchPage.fillSequence(SAMPLE_SEQUENCE)
    await searchPage.clickSubmit()

    await expect(searchPage.taskId).toHaveText(uniqueId, { timeout: 5_000 })
  })

  test('times fields rendered in correct units (ms)', async ({ page }) => {
    await page.route('/query/submit', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ task_id: MOCK_TASK_ID }),
      })
    })
    await page.route(`/query/result/${MOCK_TASK_ID}`, async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'done',
          result: [],
          times: { total_time: 2.0, esm_time: 1.5, faiss_time: 0.3, db_time: 0.2 },
        }),
      })
    })

    await searchPage.fillSequence(SAMPLE_SEQUENCE)
    await searchPage.clickSubmit()
    await searchPage.waitForStatus('done')

    const meta = await searchPage.statusMeta.textContent()
    expect(meta).toContain('2000 ms')  // total_time * 1000
    expect(meta).toContain('ESM 1500 ms')
    expect(meta).toContain('FAISS 300 ms')
    expect(meta).toContain('DB 200 ms')
  })
})
