import { useEffect, useRef } from 'react'
import { useAuthStore } from '@/features/auth/authStore'

type MessageHandler = (data: unknown) => void

const RECONNECT_DELAY_MS = 3000
const MAX_RECONNECT_ATTEMPTS = 10

// ── Shared singleton per channel key ─────────────────────────────────────────
// Key: `${tenantSchema}/${channel}`
// Multiple components subscribing to the same channel share ONE WebSocket.

interface ChannelState {
  ws: WebSocket | null
  handlers: Set<MessageHandler>
  attempts: number
  reconnectTimer: ReturnType<typeof setTimeout> | null
  url: string
}

const registry = new Map<string, ChannelState>()

function getOrCreate(key: string, url: string): ChannelState {
  if (!registry.has(key)) {
    registry.set(key, {
      ws: null,
      handlers: new Set(),
      attempts: 0,
      reconnectTimer: null,
      url,
    })
  }
  return registry.get(key)!
}

function openConnection(key: string) {
  const state = registry.get(key)
  if (!state) return
  if (state.ws && state.ws.readyState <= WebSocket.OPEN) return // already open/connecting

  const ws = new WebSocket(state.url)
  state.ws = ws

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data as string)
      state.handlers.forEach(h => h(data))
    } catch {
      // ignore malformed messages
    }
  }

  ws.onclose = (event) => {
    state.ws = null
    if (event.wasClean) return // intentional close
    if (state.handlers.size === 0) return // no one listening
    if (state.attempts >= MAX_RECONNECT_ATTEMPTS) return
    state.attempts += 1
    state.reconnectTimer = setTimeout(() => openConnection(key), RECONNECT_DELAY_MS)
  }

  ws.onerror = () => ws.close()
}

function closeIfIdle(key: string) {
  const state = registry.get(key)
  if (!state) return
  if (state.handlers.size > 0) return // still has subscribers
  if (state.reconnectTimer) { clearTimeout(state.reconnectTimer); state.reconnectTimer = null }
  state.ws?.close(1000, 'No subscribers')
  state.ws = null
  registry.delete(key)
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useWebSocket
 *
 * Connects to /ws/{tenantSchema}/{channel}?token=<jwt>.
 * All components subscribing to the same channel share a single WebSocket.
 * Auto-reconnects with a fixed delay on unexpected close.
 */
export function useWebSocket(channel: string, onMessage: MessageHandler) {
  const { accessToken, user } = useAuthStore()
  // Keep a stable ref to the latest handler so we can update it without
  // re-subscribing (avoids tearing down the shared WS on every render).
  const handlerRef = useRef<MessageHandler>(onMessage)
  handlerRef.current = onMessage

  useEffect(() => {
    if (!accessToken || !user?.tenantSchema) return

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}/ws/${user.tenantSchema}/${channel}?token=${accessToken}`
    const key = `${user.tenantSchema}/${channel}`

    // Stable wrapper — always calls the latest handler via ref
    const wrapper: MessageHandler = (data) => handlerRef.current(data)

    const state = getOrCreate(key, url)
    state.handlers.add(wrapper)
    state.attempts = 0 // reset on fresh mount
    openConnection(key)

    return () => {
      state.handlers.delete(wrapper)
      // Delay idle-close slightly so a page transition doesn't thrash the socket
      setTimeout(() => closeIfIdle(key), 500)
    }
  }, [accessToken, user?.tenantSchema, channel])
  // NOTE: onMessage is intentionally excluded — we read it via ref instead
}

