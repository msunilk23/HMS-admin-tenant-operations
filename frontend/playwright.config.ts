import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendDir = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(frontendDir, '..')
const backendDir = path.join(repoRoot, 'backend')
const pythonExecutable = process.env.E2E_PYTHON ?? path.join(repoRoot, '.venv', 'Scripts', 'python.exe')
const localPlaywrightBaseUrl = 'http://127.0.0.1:4173'
const baseURL = process.env.E2E_BASE_URL ?? localPlaywrightBaseUrl
const useManagedVite = !process.env.E2E_BASE_URL
const useManagedBackend = process.env.E2E_MANAGED_BACKEND !== 'false'
const backendPort = process.env.E2E_BACKEND_PORT ?? '8000'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: [
    ...(useManagedBackend
      ? [{
          command: `"${pythonExecutable}" -m uvicorn app.main:app --host 127.0.0.1 --port ${backendPort}`,
          url: `http://127.0.0.1:${backendPort}/health`,
          cwd: backendDir,
          reuseExistingServer: false,
          timeout: 120_000,
          env: {
            ...process.env,
            DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital',
            SECRET_KEY: process.env.SECRET_KEY ?? 'test-secret-key',
            REDIS_URL: process.env.REDIS_URL ?? 'redis://localhost:6379',
            RAZORPAY_WEBHOOK_SECRET: process.env.RAZORPAY_WEBHOOK_SECRET ?? 'e2e-webhook-secret',
          },
        }]
      : []),
    ...(useManagedVite
      ? [{
          command: 'npm run dev -- --host 127.0.0.1 --port 4173 --strictPort',
          url: localPlaywrightBaseUrl,
          cwd: frontendDir,
          reuseExistingServer: false,
          timeout: 120_000,
        }]
      : []),
  ],
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  globalSetup: path.join(frontendDir, 'e2e', 'global-setup.ts'),
  globalTeardown: path.join(frontendDir, 'e2e', 'global-teardown.ts'),
})
