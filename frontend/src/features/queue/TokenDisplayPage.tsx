/**
 * Token Display Board — public TV screen for the waiting area.
 * Route: /display/:tenantSchema/:displayToken  (no auth — revocable per-tenant credential)
 *
 * Connects to WebSocket to receive real-time queue updates.
 * Never renders patient-identifying information (name, UHID, phone) or
 * clinical/emergency labels — see backend app/api/v1/queue.py token_issued
 * broadcast, which intentionally omits PII from this channel's payload.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams } from 'react-router-dom'

interface TokenEntry {
  token_no: number
  queue_type: string
  department_name?: string
  doctor_name?: string
  is_priority?: boolean
  status: string
  issued_at: string
}

const QUEUE_LABEL: Record<string, string> = {
  registration: 'Registration',
  vitals: 'Vitals',
  consultation: 'Consultation',
  pharmacy: 'Pharmacy',
  billing: 'Billing',
}

export default function TokenDisplayPage() {
  const { tenantSchema, displayToken } = useParams<{ tenantSchema: string; displayToken: string }>()
  const [calledTokens, setCalledTokens] = useState<TokenEntry[]>([])
  const [currentTime, setCurrentTime] = useState(new Date())
  const wsRef = useRef<WebSocket | null>(null)

  // Clock tick
  useEffect(() => {
    const id = setInterval(() => setCurrentTime(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  // WebSocket connection (no auth — public display, revocable per-tenant credential)
  const connect = useCallback(() => {
    if (!tenantSchema || !displayToken) return
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}/ws/${tenantSchema}/queue:update?token=${encodeURIComponent(displayToken)}`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.event === 'token_issued' || data.event === 'token_updated') {
          if (data.status === 'called' || data.event === 'token_issued') {
            setCalledTokens(prev => {
              const next: TokenEntry = {
                token_no: data.token_no,
                queue_type: data.queue_type,
                department_name: data.department_name,
                doctor_name: data.doctor_name,
                is_priority: !!data.is_priority,
                status: data.status ?? 'waiting',
                issued_at: new Date().toISOString(),
              }
              // Put newly called tokens at top, keep last 12
              const filtered = prev.filter(t => t.token_no !== data.token_no)
              return [next, ...filtered].slice(0, 12)
            })
          }
        }
      } catch {
        // ignore
      }
    }

    ws.onclose = (event) => {
      if (event.code !== 1000) setTimeout(connect, 3000)
    }
  }, [tenantSchema, displayToken])

  useEffect(() => {
    connect()
    return () => wsRef.current?.close(1000)
  }, [connect])

  const nowCalled = calledTokens.filter(t => t.status === 'called' || t.status === 'in_progress')
  const recentWaiting = calledTokens.filter(t => t.status !== 'called' && t.status !== 'in_progress')

  return (
    <div className="min-h-screen bg-gray-950 text-white flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-8 py-5 border-b border-gray-800">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-blue-600 rounded-xl flex items-center justify-center">
            <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
            </svg>
          </div>
          <div>
            <h1 className="text-xl font-bold">OPD Token Display</h1>
            <p className="text-xs text-gray-400 capitalize">{tenantSchema?.replace(/_/g, ' ')}</p>
          </div>
        </div>
        <div className="text-right">
          <p className="text-3xl font-mono font-bold text-blue-400">
            {currentTime.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </p>
          <p className="text-xs text-gray-400">
            {currentTime.toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
          </p>
        </div>
      </div>

      {/* Main content */}
      <div className="flex flex-1 gap-0">
        {/* NOW SERVING — large center panel */}
        <div className="flex-1 flex flex-col items-center justify-center p-12 border-r border-gray-800">
          <p className="text-sm font-semibold text-gray-400 uppercase tracking-widest mb-6">Now Serving</p>

          {nowCalled.length === 0 ? (
            <div className="text-center">
              <div className="w-32 h-32 border-4 border-gray-700 rounded-full flex items-center justify-center mx-auto mb-4">
                <span className="text-gray-600 text-5xl font-bold">—</span>
              </div>
              <p className="text-gray-500">No token called yet</p>
            </div>
          ) : (
            <div className="space-y-6 w-full max-w-xs">
              {nowCalled.slice(0, 3).map((t, i) => (
                <div key={i}
                  className={`rounded-2xl border-2 p-6 text-center ${
                    i === 0
                      ? 'border-blue-500 bg-blue-900/30 shadow-lg shadow-blue-900/30'
                      : 'border-gray-700 bg-gray-900'
                  }`}
                >
                  {t.is_priority && (
                    <span className="inline-block bg-amber-600 text-white text-xs font-bold px-2 py-0.5 rounded-full mb-2">
                      PRIORITY
                    </span>
                  )}
                  <p className={`font-mono font-black ${i === 0 ? 'text-8xl text-blue-400' : 'text-5xl text-gray-300'}`}>
                    {t.token_no}
                  </p>
                  <p className="text-sm text-gray-400 mt-2">{QUEUE_LABEL[t.queue_type] ?? t.queue_type}</p>
                  {(t.department_name || t.doctor_name) && (
                    <p className="text-xs text-gray-500 mt-1">
                      {[t.department_name, t.doctor_name].filter(Boolean).join(' · ')}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Recent tokens — right sidebar */}
        <div className="w-80 flex flex-col border-l border-gray-800">
          <div className="px-5 py-4 border-b border-gray-800">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest">Queue</p>
          </div>
          <div className="flex-1 overflow-y-auto divide-y divide-gray-800">
            {recentWaiting.length === 0 ? (
              <div className="px-5 py-8 text-center text-gray-600 text-sm">No pending tokens</div>
            ) : recentWaiting.map((t, i) => (
              <div key={i} className="flex items-center justify-between px-5 py-3">
                <div className="flex items-center gap-3">
                  <span className="text-2xl font-bold font-mono text-gray-300 tabular-nums w-12 text-right">
                    {t.token_no}
                  </span>
                  <div>
                    <p className="text-sm text-gray-400">{QUEUE_LABEL[t.queue_type] ?? t.queue_type}</p>
                    {t.is_priority && (
                      <span className="text-xs text-amber-400">priority</span>
                    )}
                  </div>
                </div>
                <span className={`w-2 h-2 rounded-full ${t.status === 'waiting' ? 'bg-blue-500' : 'bg-gray-600'}`} />
              </div>
            ))}
          </div>

          {/* Footer ticker */}
          <div className="px-5 py-3 border-t border-gray-800 bg-blue-900/20">
            <p className="text-xs text-blue-400 text-center">
              Please follow COVID-19 safety protocols · Wear your mask
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
