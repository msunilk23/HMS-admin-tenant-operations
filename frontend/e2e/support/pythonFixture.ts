import { execFileSync, type ExecFileSyncOptionsWithStringEncoding } from 'node:child_process'

export function resolveE2EPython(): string {
  return process.env.E2E_PYTHON ?? process.env.PYTHON ?? 'python'
}

export function runPythonFixture(
  args: string[],
  options: ExecFileSyncOptionsWithStringEncoding,
): string {
  const executable = resolveE2EPython()
  try {
    return execFileSync(executable, args, options)
  } catch (error) {
    const selectedBy = process.env.E2E_PYTHON ? 'E2E_PYTHON' : process.env.PYTHON ? 'PYTHON' : 'default python'
    throw new Error(`E2E Python fixture failed using ${selectedBy}: ${error instanceof Error ? error.message : String(error)}`)
  }
}
