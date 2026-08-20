/**
 * POS Screen — PAX A920 / tablet kiosk payment display.
 *
 * URL: /pos/:tenantSchema
 *
 * No login required. Connects to the `pos:payment` WebSocket channel.
 * Listens for `payment_request` events → opens Razorpay checkout modal.
 * Listens for `payment_success` events → shows success, returns to idle.
 */
import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'

type PosState = 'idle' | 'payment_pending' | 'payment_success'

interface PaymentRequest {
  razorpay_key_id: string
  razorpay_order_id: string | null
  invoice_id: string
  amount: number          // paise
  amount_display: string  // e.g. "₹500"
  patient_name: string
  uhid: string
  description: string
}

interface PaymentSuccess {
  razorpay_order_id: string
  payment_method: string
}

declare global {
  interface Window {
    Razorpay: any
  }
}

function loadRazorpayScript(): Promise<boolean> {
  return new Promise((resolve) => {
    if (window.Razorpay) { resolve(true); return }
    const script = document.createElement('script')
    script.src = 'https://checkout.razorpay.com/v1/checkout.js'
    script.onload = () => resolve(true)
    script.onerror = () => resolve(false)
    document.body.appendChild(script)
  })
}

export default function PosScreen() {
  const { tenantSchema } = useParams<{ tenantSchema: string }>()
  const [posState, setPosState] = useState<PosState>('idle')
  const [paymentReq, setPaymentReq] = useState<PaymentRequest | null>(null)
  const [successInfo, setSuccessInfo] = useState<PaymentSuccess | null>(null)
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'reconnecting'>('connecting')
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── WebSocket connection ─────────────────────────────────────────────────
  useEffect(() => {
    if (!tenantSchema) return

    function connect() {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const url = `${protocol}://${window.location.host}/ws/${tenantSchema}/pos:payment?token=kiosk`
      const ws = new WebSocket(url)
      wsRef.current = ws
      setWsStatus('connecting')

      ws.onopen = () => setWsStatus('connected')

      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data as string)
          handleMessage(msg)
        } catch { /* ignore malformed */ }
      }

      ws.onclose = (e) => {
        if (e.wasClean) return
        setWsStatus('reconnecting')
        reconnectTimer.current = setTimeout(connect, 3000)
      }

      ws.onerror = () => ws.close()
    }

    connect()

    // Keep-alive ping
    const ping = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send('ping')
      }
    }, 25000)

    return () => {
      clearInterval(ping)
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      wsRef.current?.close(1000, 'unmount')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantSchema])

  // ── Auto-return to idle after success ────────────────────────────────────
  useEffect(() => {
    if (posState !== 'payment_success') return
    const t = setTimeout(() => {
      setPosState('idle')
      setSuccessInfo(null)
      setPaymentReq(null)
    }, 6000)
    return () => clearTimeout(t)
  }, [posState])

  // ── Message handler ───────────────────────────────────────────────────────
  async function handleMessage(msg: Record<string, unknown>) {
    console.log('[PosScreen] Message received:', msg)
    
    if (msg.event === 'payment_request') {
      const req = msg as unknown as PaymentRequest & { event: string }
      console.log('[PosScreen] Payment request - key:', req.razorpay_key_id, 'order:', req.razorpay_order_id)
      
      if (!req.razorpay_key_id) {
        console.error('[PosScreen] ❌ razorpay_key_id is missing or undefined!')
      }
      if (!req.razorpay_order_id) {
        console.error('[PosScreen] ❌ razorpay_order_id is missing or undefined!')
      }
      
      setPaymentReq(req)
      setPosState('payment_pending')
      await openRazorpayCheckout(req)
    } else if (msg.event === 'payment_success') {
      const info = msg as unknown as PaymentSuccess & { event: string }
      console.log('[PosScreen] Payment success:', info)
      setSuccessInfo(info)
      setPosState('payment_success')
    }
  }

  // ── Razorpay checkout ─────────────────────────────────────────────────────
  async function openRazorpayCheckout(req: PaymentRequest) {
    console.log('[PosScreen] openRazorpayCheckout() called with:', req)
    
    const loaded = await loadRazorpayScript()
    if (!loaded || !window.Razorpay) {
      console.error('Razorpay checkout.js failed to load')
      return
    }
    if (!req.razorpay_key_id || !req.razorpay_order_id) {
      console.warn('[PosScreen] ⚠️  Razorpay not properly configured. key_id:', req.razorpay_key_id, 'order_id:', req.razorpay_order_id)
      console.error('[PosScreen] ❌ Cannot proceed with payment. Missing key_id or order_id')
      // Show error and return to idle
      setPosState('idle')
      return
    }

    const options = {
      key: req.razorpay_key_id,
      amount: req.amount,
      currency: 'INR',
      order_id: req.razorpay_order_id,
      name: 'Hospital Payment',
      description: req.description,
      prefill: { name: req.patient_name },
      theme: { color: '#1d4ed8' },
      modal: {
        backdropclose: false,
        escape: false,
        animation: true,
        ondismiss: () => {
          // If checkout dismissed without payment, stay in payment_pending
          // so receptionist can retry — don't reset to idle
        },
      },
      redirect: false,   // always use popup, never redirect the page
      handler: () => {
        // Payment captured on client side — webhook will confirm and push payment_success
        // Just show a "processing" state; WS will deliver payment_success shortly
      },
    }

    console.log('[PosScreen] Creating Razorpay with options:', options)
    const rzp = new window.Razorpay(options)
    console.log('[PosScreen] Razorpay initialized, opening modal...')
    rzp.open()
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-950 text-white flex flex-col items-center justify-center select-none">
      {/* Status dot */}
      <div className="absolute top-4 right-4 flex items-center gap-2 text-xs text-gray-500">
        <span
          className={`w-2 h-2 rounded-full ${
            wsStatus === 'connected' ? 'bg-green-500' :
            wsStatus === 'reconnecting' ? 'bg-yellow-500 animate-pulse' :
            'bg-gray-500 animate-pulse'
          }`}
        />
        {wsStatus}
      </div>

      {posState === 'idle' && (
        <div className="flex flex-col items-center gap-6 text-center px-8">
          <div className="w-24 h-24 rounded-full bg-blue-900/40 flex items-center justify-center">
            <svg className="w-12 h-12 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-2 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
            </svg>
          </div>
          <h1 className="text-3xl font-bold text-white">Waiting for payment…</h1>
          <p className="text-gray-400 text-lg">Please wait at the reception for your token</p>
        </div>
      )}

      {posState === 'payment_pending' && paymentReq && (
        <div className="flex flex-col items-center gap-6 text-center px-8 w-full max-w-sm">
          <div className="w-full bg-gray-900 rounded-2xl p-6 space-y-4 border border-gray-800">
            <p className="text-gray-400 text-sm uppercase tracking-widest">Amount Due</p>
            <p className="text-5xl font-extrabold text-white">{paymentReq.amount_display}</p>
            <div className="border-t border-gray-800 pt-4 space-y-1">
              <p className="text-white font-semibold text-lg">{paymentReq.patient_name}</p>
              <p className="text-gray-500 text-sm">{paymentReq.uhid}</p>
              <p className="text-gray-400 text-sm mt-1">{paymentReq.description}</p>
            </div>
          </div>

          {/* Shown when Razorpay not configured (no order_id) */}
          {!paymentReq.razorpay_order_id && (
            <div className="text-center text-gray-400 text-sm space-y-1">
              <p>Razorpay not configured.</p>
              <p>Please collect payment manually.</p>
            </div>
          )}

          {paymentReq.razorpay_order_id && (
            <p className="text-blue-400 text-sm animate-pulse">
              Complete payment in the popup window…
            </p>
          )}
        </div>
      )}

      {posState === 'payment_success' && (
        <div className="flex flex-col items-center gap-6 text-center px-8 animate-in fade-in duration-500">
          <div className="w-24 h-24 rounded-full bg-green-500/20 flex items-center justify-center">
            <svg className="w-14 h-14 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h1 className="text-4xl font-extrabold text-green-400">Payment Received</h1>
          {successInfo?.payment_method && (
            <p className="text-gray-400 text-lg capitalize">
              via {successInfo.payment_method.toUpperCase()}
            </p>
          )}
          <p className="text-gray-500 text-sm mt-2">Thank you! Please proceed to the waiting area.</p>
        </div>
      )}
    </div>
  )
}
