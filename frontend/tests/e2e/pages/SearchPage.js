import { expect } from '@playwright/test'

/**
 * Page Object Model for the Protein FAISS Search page.
 * All selectors use data-testid attributes for stability.
 */
export class SearchPage {
  constructor(page) {
    this.page = page

    // Input section
    this.sequenceInput = page.locator('[data-testid="sequence-input"]')
    this.topkInput = page.locator('[data-testid="topk-input"]')
    this.poolingSelect = page.locator('[data-testid="pooling-select"]')
    this.submitBtn = page.locator('[data-testid="submit-btn"]')
    this.cancelBtn = page.locator('[data-testid="cancel-btn"]')

    // Status panel
    this.statusPanel = page.locator('[data-testid="status-panel"]')
    this.statusChip = page.locator('[data-testid="status-chip"]')
    this.taskId = page.locator('[data-testid="task-id"]')
    this.statusMeta = page.locator('[data-testid="status-meta"]')

    // Results panel
    this.resultsPanel = page.locator('[data-testid="results-panel"]')
    this.resultItems = page.locator('[data-testid="result-item"]')
    this.noResults = page.locator('[data-testid="no-results"]')

    // Diagnostic log
    this.logPanel = page.locator('[data-testid="log-panel"]')
    this.logArea = page.locator('[data-testid="log-area"]')
    this.logToggle = page.locator('[data-testid="log-toggle"]')
  }

  async goto() {
    await this.page.goto('/')
    await this.page.waitForLoadState('networkidle')
  }

  async fillSequence(seq) {
    await this.sequenceInput.fill(seq)
  }

  async setTopK(n) {
    await this.topkInput.fill(String(n))
  }

  async setPooling(value) {
    await this.poolingSelect.selectOption(value)
  }

  async clickSubmit() {
    await this.submitBtn.click()
  }

  async clickCancel() {
    await this.cancelBtn.click()
  }

  async waitForStatus(status, { timeout = 10_000 } = {}) {
    await expect(this.statusChip).toHaveText(status, { timeout })
  }

  async waitForResults({ timeout = 10_000 } = {}) {
    await expect(this.resultsPanel).toBeVisible({ timeout })
  }

  async getResultCount() {
    return await this.resultItems.count()
  }
}
