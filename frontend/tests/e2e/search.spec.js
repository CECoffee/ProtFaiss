import { test, expect } from '@playwright/test'
import { SearchPage } from './pages/SearchPage.js'
import {
  mockSuccessFlow,
  mockPendingThenDone,
  mockBackendError,
  mockSubmitFailure,
  mockPoll404,
  SAMPLE_SEQUENCE,
  MOCK_TASK_ID,
  MOCK_RESULTS,
} from './fixtures/api.js'

test.describe('Protein Search — submit → poll → results', () => {
  let searchPage

  test.beforeEach(async ({ page }) => {
    searchPage = new SearchPage(page)
    await searchPage.goto()
  })

  // ── Happy path ──────────────────────────────────────────────────

  test('renders the input form on load', async ({ page }) => {
    await expect(searchPage.sequenceInput).toBeVisible()
    await expect(searchPage.topkInput).toHaveValue('5')
    await expect(searchPage.poolingSelect).toHaveValue('mean')
    await expect(searchPage.submitBtn).toBeVisible()
    await expect(searchPage.cancelBtn).toBeVisible()
    await expect(searchPage.statusPanel).not.toBeVisible()
    await expect(searchPage.resultsPanel).not.toBeVisible()
  })

  test('submit sequence → poll → display results', async ({ page }) => {
    await mockSuccessFlow(page)

    await searchPage.fillSequence(SAMPLE_SEQUENCE)
    await searchPage.clickSubmit()

    // Status panel appears and shows task ID
    await expect(searchPage.statusPanel).toBeVisible()
    await expect(searchPage.taskId).toHaveText(MOCK_TASK_ID)

    // Wait for done status
    await searchPage.waitForStatus('done')
    await expect(searchPage.statusChip).toHaveClass(/chip--done/)

    // Timing metadata shown in meta line
    const meta = await searchPage.statusMeta.textContent()
    expect(meta).toContain('完成')
    expect(meta).toMatch(/ESM.*ms/)

    // Results panel appears with correct count
    await searchPage.waitForResults()
    expect(await searchPage.getResultCount()).toBe(MOCK_RESULTS.length)

    // First result card content
    const firstItem = searchPage.resultItems.first()
    await expect(firstItem.locator('[data-testid="result-distance"]')).toContainText('0.1234')
    await expect(firstItem.locator('[data-testid="result-annotations"]')).toContainText('K00001')
    await expect(firstItem.locator('[data-testid="result-annotations"]')).toContainText('1.1.1.1')

    // Diagnostic log appears
    await expect(searchPage.logPanel).toBeVisible()
    await expect(searchPage.logArea).toContainText(`/query/result/${MOCK_TASK_ID}`)

    await page.screenshot({ path: 'playwright-artifacts/happy-path-done.png' })
  })

  test('shows pending status during multiple poll attempts before done', async ({ page }) => {
    await mockPendingThenDone(page, { pendingCount: 2 })

    await searchPage.fillSequence(SAMPLE_SEQUENCE)
    await searchPage.clickSubmit()

    // Should eventually reach done despite 2 pending responses
    await searchPage.waitForStatus('done', { timeout: 15_000 })
    await searchPage.waitForResults({ timeout: 5_000 })

    const meta = await searchPage.statusMeta.textContent()
    expect(meta).toContain('轮询次数 3') // 2 pending + 1 done
  })

  test('configures top-k and pooling before submit', async ({ page }) => {
    let capturedBody = null
    await page.route('/query/submit', async route => {
      capturedBody = JSON.parse(route.request().postData())
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
    await searchPage.setTopK(10)
    await searchPage.setPooling('max')
    await searchPage.clickSubmit()

    await searchPage.waitForStatus('done', { timeout: 10_000 })

    expect(capturedBody.top_k).toBe(10)
    expect(capturedBody.pooling).toBe('max')
    expect(capturedBody.sequence).toBe(SAMPLE_SEQUENCE)
  })

  // ── Empty input validation ────────────────────────────────────

  test('shows alert when submitting empty sequence', async ({ page }) => {
    const dialogMessages = []
    page.on('dialog', async dialog => {
      dialogMessages.push(dialog.message())
      await dialog.accept()
    })

    await searchPage.clickSubmit()

    expect(dialogMessages.length).toBe(1)
    expect(dialogMessages[0]).toContain('请填写查询序列')

    // Status panel should NOT appear
    await expect(searchPage.statusPanel).not.toBeVisible()
  })

  // ── Cancel polling ────────────────────────────────────────────

  test('cancel button aborts polling and shows cancelled status', async ({ page }) => {
    // Keep poll permanently pending so we can cancel
    await page.route('/query/submit', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ task_id: MOCK_TASK_ID }),
      })
    })
    await page.route(`/query/result/${MOCK_TASK_ID}`, async route => {
      // Never resolve to done
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'pending' }),
      })
    })

    await searchPage.fillSequence(SAMPLE_SEQUENCE)
    await searchPage.clickSubmit()

    // Wait for at least one poll attempt
    await searchPage.waitForStatus('pending')
    await expect(searchPage.logPanel).toBeVisible()

    // Cancel
    await searchPage.clickCancel()

    await searchPage.waitForStatus('cancelled')
    await expect(searchPage.statusChip).toHaveClass(/chip--cancelled/)

    // Log should mention cancellation
    await expect(searchPage.logArea).toContainText('取消')

    // Results panel should NOT appear
    await expect(searchPage.resultsPanel).not.toBeVisible()

    await page.screenshot({ path: 'playwright-artifacts/cancelled.png' })
  })

  test('cancel when not polling shows alert', async ({ page }) => {
    const dialogMessages = []
    page.on('dialog', async dialog => {
      dialogMessages.push(dialog.message())
      await dialog.accept()
    })

    await searchPage.clickCancel()

    expect(dialogMessages.length).toBe(1)
    expect(dialogMessages[0]).toContain('没有正在轮询的任务')
  })

  // ── Error states ──────────────────────────────────────────────

  test('shows error status when backend reports task error', async ({ page }) => {
    await mockBackendError(page, { errorMsg: 'GPU OOM during encoding' })

    await searchPage.fillSequence(SAMPLE_SEQUENCE)
    await searchPage.clickSubmit()

    await searchPage.waitForStatus('error')
    await expect(searchPage.statusChip).toHaveClass(/chip--error/)

    const meta = await searchPage.statusMeta.textContent()
    expect(meta).toContain('GPU OOM during encoding')

    await expect(searchPage.resultsPanel).not.toBeVisible()
  })

  test('shows error status when poll returns 404', async ({ page }) => {
    await mockPoll404(page)

    await searchPage.fillSequence(SAMPLE_SEQUENCE)
    await searchPage.clickSubmit()

    await searchPage.waitForStatus('error')

    const meta = await searchPage.statusMeta.textContent()
    expect(meta).toContain('404')
  })

  test('shows empty results state when result array is empty', async ({ page }) => {
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
        body: JSON.stringify({ status: 'done', result: [], times: {} }),
      })
    })

    await searchPage.fillSequence(SAMPLE_SEQUENCE)
    await searchPage.clickSubmit()

    await searchPage.waitForStatus('done')
    await searchPage.waitForResults()

    await expect(searchPage.noResults).toBeVisible()
    await expect(searchPage.noResults).toContainText('未返回结果')
    expect(await searchPage.getResultCount()).toBe(0)
  })

  // ── Diagnostic log ────────────────────────────────────────────

  test('log panel can be collapsed and expanded', async ({ page }) => {
    await mockSuccessFlow(page)

    await searchPage.fillSequence(SAMPLE_SEQUENCE)
    await searchPage.clickSubmit()

    await searchPage.waitForStatus('done')
    await expect(searchPage.logPanel).toBeVisible()
    await expect(searchPage.logArea).toBeVisible()

    // Collapse
    await searchPage.logToggle.click()
    await expect(searchPage.logArea).not.toBeVisible()

    // Expand again
    await searchPage.logToggle.click()
    await expect(searchPage.logArea).toBeVisible()
  })
})
