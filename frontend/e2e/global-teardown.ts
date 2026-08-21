import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export default async function globalTeardown() {
  const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
  execFileSync(process.env.PYTHON ?? 'python', [path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'), 'cleanup'], {
    cwd: path.join(repoRoot, 'backend'),
    stdio: 'inherit',
    env: { ...process.env, DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital', SECRET_KEY: process.env.SECRET_KEY ?? 'test-secret-key' },
  })
}
