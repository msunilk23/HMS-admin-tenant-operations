import { describe, expect, it, beforeEach } from 'vitest'
import { useAuthStore } from './authStore'

function token(payload: Record<string, unknown>): string {
  const encode = (value: Record<string, unknown>) => Buffer.from(JSON.stringify(value)).toString('base64url')
  return `${encode({ alg: 'none', typ: 'JWT' })}.${encode(payload)}.signature`
}

describe('auth store security state', () => {
  beforeEach(() => {
    useAuthStore.getState().logout()
  })

  it('stores token claims and authoritative feature claims', () => {
    useAuthStore.getState().setTokens(token({
      sub: 'user-a', exp: Math.floor(Date.now() / 1000) + 300,
      role: 'doctor', tenant_schema: 'hospital-a', features: ['billing'],
    }), 'refresh-a')

    const state = useAuthStore.getState()
    expect(state.user?.id).toBe('user-a')
    expect(state.user?.tenantSchema).toBe('hospital-a')
    expect(state.hasFeature('billing')).toBe(true)
    expect(state.hasFeature('pharmacy')).toBe(false)
  })

  it('rejects tokens without an expiry and clears expired sessions', () => {
    useAuthStore.getState().setTokens(token({ sub: 'user-a', role: 'doctor' }), 'refresh-a')
    expect(useAuthStore.getState().isAuthenticated()).toBe(false)

    useAuthStore.getState().setTokens(token({
      sub: 'user-b', exp: Math.floor(Date.now() / 1000) - 1, role: 'doctor',
    }), 'refresh-b')
    expect(useAuthStore.getState().isAuthenticated()).toBe(false)
  })
})