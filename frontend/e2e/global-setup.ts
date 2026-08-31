import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

async function waitForHttp(url: string, timeoutMs: number, label: string): Promise<void> {
  const startedAt = Date.now()
  let lastError = 'no response received'
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch(url, { method: 'GET' })
      if (response.ok) return
      lastError = `HTTP ${response.status}`
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error)
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  throw new Error(`${label} not ready at ${url} within ${timeoutMs}ms (${lastError})`)
}

async function verifyBackendContract(openApiUrl: string): Promise<void> {
  const response = await fetch(openApiUrl, { method: 'GET' })
  if (!response.ok) {
    throw new Error(`OpenAPI contract check failed with HTTP ${response.status} at ${openApiUrl}`)
  }
  const payload = (await response.json()) as { paths?: Record<string, unknown> }
  const paths = new Set(Object.keys(payload.paths ?? {}))
  const requiredPaths = [
    '/api/v1/pharmacy/{pq_id}/start',
    '/api/v1/pharmacy/dispenses/{dispense_id}/validate',
    '/api/v1/pharmacy/dispenses/{dispense_id}/reserve',
    '/api/v1/pharmacy/dispenses/{dispense_id}/confirm',
  ]
  const missing = requiredPaths.filter((path) => !paths.has(path))
  if (missing.length > 0) {
    throw new Error(
      `Backend does not expose required P28 routes (${missing.join(', ')}). ` +
      'This usually means a stale or wrong backend process is running for E2E.',
    )
  }
}

function runBackendCommand(repoRoot: string, args: string[]): void {
  execFileSync(process.env.E2E_PYTHON ?? process.env.PYTHON ?? 'python', args, {
    cwd: path.join(repoRoot, 'backend'),
    stdio: 'inherit',
    env: {
      ...process.env,
      DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital',
      SECRET_KEY: process.env.SECRET_KEY ?? 'test-secret-key',
      REDIS_URL: process.env.REDIS_URL ?? 'redis://localhost:6379',
    },
  })
}

export default async function globalSetup() {
  process.env.E2E_ENVIRONMENT = 'E2E'
  const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
  const backendHealthUrl = process.env.E2E_BACKEND_HEALTH_URL ?? 'http://127.0.0.1:8000/health'
  const openApiUrl = process.env.E2E_BACKEND_OPENAPI_URL ?? 'http://127.0.0.1:8000/api/openapi.json'
  runBackendCommand(repoRoot, ['-m', 'alembic', 'upgrade', 'head'])
  await waitForHttp(backendHealthUrl, 120_000, 'Backend health')
  await verifyBackendContract(openApiUrl)
  execFileSync(process.env.E2E_PYTHON ?? process.env.PYTHON ?? 'python', [path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'), 'seed'], {
    cwd: path.join(repoRoot, 'backend'),
    stdio: 'inherit',
    env: {
      ...process.env,
      E2E_ALLOW_DESTRUCTIVE_RESET: 'true',
      DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital',
      SECRET_KEY: process.env.SECRET_KEY ?? 'test-secret-key',
      REDIS_URL: process.env.REDIS_URL ?? 'redis://localhost:6379',
    },
  })
}
