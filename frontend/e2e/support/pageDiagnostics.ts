import type { Page, TestInfo } from '@playwright/test'
import fs from 'node:fs'

type ResponseRecord = {
  url: string
  status: number
  resourceType: string
}

type RequestFailureRecord = {
  url: string
  method: string
  resourceType: string
  errorText: string
}

type PageErrorRecord = {
  message: string
  stack: string | undefined
}

export type PageDiagnosticsCollector = {
  flush: (testInfo: TestInfo) => Promise<void>
}

export function createPageDiagnostics(page: Page): PageDiagnosticsCollector {
  const consoleMessages: string[] = []
  const pageErrors: PageErrorRecord[] = []
  const failedRequests: RequestFailureRecord[] = []
  const responses: ResponseRecord[] = []

  page.on('console', (message) => {
    consoleMessages.push(`[${message.type()}] ${message.text()}`)
  })

  page.on('pageerror', (error) => {
    pageErrors.push({ message: error.message, stack: error.stack })
  })

  page.on('requestfailed', (request) => {
    failedRequests.push({
      url: request.url(),
      method: request.method(),
      resourceType: request.resourceType(),
      errorText: request.failure()?.errorText ?? 'unknown',
    })
  })

  page.on('response', (response) => {
    const request = response.request()
    const resourceType = request.resourceType()
    const shouldRecord =
      resourceType === 'script' ||
      resourceType === 'stylesheet' ||
      resourceType === 'document' ||
      response.url().includes('/api/')
    if (!shouldRecord) return
    responses.push({ url: response.url(), status: response.status(), resourceType })
  })

  return {
    flush: async (testInfo: TestInfo) => {
    if (testInfo.status === testInfo.expectedStatus) return

    const screenshotPath = testInfo.outputPath('diagnostics-failure.png')
    await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => undefined)

    const htmlPath = testInfo.outputPath('diagnostics-page.html')
    const html = await page.content().catch(() => '<html><body>Failed to capture HTML</body></html>')
    fs.writeFileSync(htmlPath, html, 'utf8')

    const payload = {
      url: page.url(),
      console: consoleMessages,
      pageErrors,
      failedRequests,
      responses,
    }
    const jsonPath = testInfo.outputPath('diagnostics.json')
    fs.writeFileSync(jsonPath, JSON.stringify(payload, null, 2), 'utf8')

    await testInfo.attach('diagnostics-json', {
      path: jsonPath,
      contentType: 'application/json',
    })
    await testInfo.attach('diagnostics-html', {
      path: htmlPath,
      contentType: 'text/html',
    })
    await testInfo.attach('diagnostics-screenshot', {
      path: screenshotPath,
      contentType: 'image/png',
    })
    },
  }
}
