/**
 * Admin Dashboard — Command Center for hospital_admin
 *
 * Row 1: 4 KPI summary cards (patients, OPD, staff, revenue)
 * Row 2: 3 service panels (Pharmacy, Lab, Billing)
 * Row 3: Department performance table (all-time)
 * Row 4: Today's OPD summary + Appointments breakdown
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '@/services/apiClient'
import { tenantService } from '@/services/tenantService'

interface StaffRole { role: string; count: number }
interface DeptStat { name: string; total: number; completed: number; in_progress: number }

interface AdminStats {
  total_patients: number
  new_patients_today: number
  total_staff: number
  staff_by_role: StaffRole[]
  visits_today: number
  visits_completed_today: number
  visits_in_progress_today: number
  appointments_today: number
  appointments_completed_today: number
  appointments_cancelled_today: number
  departments: DeptStat[]
  pharmacy_dispensed: number
  pharmacy_pending: number
  pharmacy_total: number
  lab_resulted: number
  lab_rejected: number
  lab_pending: number
  lab_total: number
  revenue_today: number
  revenue_total: number
  invoices_paid_today: number
  invoices_draft: number
}

interface IndentStats {
  period: string
  since: string
  total_indents: number
  total_expenditure: number
  fulfilled_count: number
  fulfilled_amount: number
  pending_count: number
  approved_count: number
  by_date: { date: string; amount: number }[]
}

const ROLE_LABELS: Record<string, string> = {
  receptionist: 'Receptionist',
  nurse: 'Nurse',
  doctor: 'Doctor',
  lab_technician: 'Lab Tech',
  pharmacist: 'Pharmacist',
  billing_officer: 'Billing',
  hospital_admin: 'Admin',
  store_manager: 'Store Manager',
  super_admin: 'Super Admin',
}

function fmt(n: number) {
  return n.toLocaleString('en-IN')
}
function fmtCurrency(n: number) {
  return '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: 0 })
}

function ProgressBar({ value, total, color }: { value: number; total: number; color: string }) {
  const pct = total > 0 ? Math.min(100, Math.round((value / total) * 100)) : 0
  return (
    <div className="w-full bg-gray-100 rounded-full h-2 mt-1">
      <div className={`h-2 rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

function KPICard({
  label, value, sub, accent, icon,
}: {
  label: string; value: string | number; sub?: string; accent: string; icon: React.ReactNode
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm flex gap-4 items-start">
      <div className={`p-2.5 rounded-lg ${accent} shrink-0`}>{icon}</div>
      <div className="min-w-0">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{label}</p>
        <p className="text-3xl font-bold text-gray-900 mt-0.5">{value}</p>
        {sub && <p className="text-xs text-gray-400 mt-1 leading-relaxed">{sub}</p>}
      </div>
    </div>
  )
}

function SkeletonCard({ h = 'h-32' }: { h?: string }) {
  return <div className={`${h} bg-gray-100 rounded-xl animate-pulse`} />
}

function DisplayBoardCard() {
  const qc = useQueryClient()
  const [copied, setCopied] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['display-token'],
    queryFn: () => tenantService.getDisplayToken(),
  })

  const { mutate: rotate, isPending: rotating } = useMutation({
    mutationFn: () => tenantService.rotateDisplayToken(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['display-token'] }),
  })

  const fullUrl = data ? `${window.location.origin}${data.display_url_path}` : ''

  const copyUrl = async () => {
    if (!fullUrl) return
    await navigator.clipboard.writeText(fullUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-gray-700">Waiting-Room Display Board</span>
        <span className="text-xs text-gray-400">No patient details are ever shown on this screen</span>
      </div>
      {isLoading || !data ? (
        <div className="h-10 bg-gray-100 rounded-lg animate-pulse" />
      ) : (
        <div className="flex flex-col sm:flex-row gap-3 sm:items-center">
          <input
            readOnly
            value={fullUrl}
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-xs text-gray-600 bg-gray-50"
          />
          <div className="flex gap-2 shrink-0">
            <button
              onClick={copyUrl}
              className="px-3 py-2 rounded-lg border border-gray-300 text-xs font-medium text-gray-700 hover:bg-gray-50"
            >
              {copied ? 'Copied!' : 'Copy URL'}
            </button>
            <button
              onClick={() => {
                if (confirm('Rotating will immediately disconnect any TV boards using the current URL. Continue?')) rotate()
              }}
              disabled={rotating}
              className="px-3 py-2 rounded-lg border border-red-200 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
            >
              {rotating ? 'Rotating…' : 'Revoke & Rotate'}
            </button>
          </div>
        </div>
      )}
      <p className="text-xs text-gray-400 mt-2">
        Open this URL on the waiting-area TV/display board. Rotating immediately revokes the old link.
      </p>
    </div>
  )
}

export default function AdminDashboard() {
  const [indentPeriod, setIndentPeriod] = useState<'week' | 'month' | 'year'>('month')

  const { data: s, isLoading, dataUpdatedAt } = useQuery<AdminStats>({
    queryKey: ['admin-stats'],
    queryFn: () => apiClient.get('/admin/stats').then(r => r.data),
    refetchInterval: 60_000,
  })

  const { data: indentStats } = useQuery<IndentStats>({
    queryKey: ['indent-stats', indentPeriod],
    queryFn: () => apiClient.get('/indents/stats', { params: { period: indentPeriod } }).then(r => r.data),
    refetchInterval: 60_000,
  })

  const todayLabel = new Date().toLocaleDateString('en-IN', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  })
  const lastRefresh = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
    : null

  if (isLoading || !s) {
    return (
      <div className="p-6 space-y-5">
        <div className="h-8 w-64 bg-gray-100 rounded-lg animate-pulse" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => <SkeletonCard key={i} h="h-44" />)}
        </div>
        <SkeletonCard h="h-64" />
        <SkeletonCard h="h-32" />
      </div>
    )
  }

  const opdRate = s.visits_today > 0 ? Math.round((s.visits_completed_today / s.visits_today) * 100) : 0
  const apptCancelRate = s.appointments_today > 0
    ? Math.round((s.appointments_cancelled_today / s.appointments_today) * 100) : 0

  const staffSummary = s.staff_by_role
    .map(r => `${ROLE_LABELS[r.role] ?? r.role} (${r.count})`)
    .join(' · ')

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Command Center</h1>
          <p className="text-sm text-gray-500 mt-0.5">{todayLabel}</p>
        </div>
        {lastRefresh && (
          <span className="text-xs text-gray-400 mt-1">Last updated {lastRefresh} · auto-refreshes every 60s</span>
        )}
      </div>

      {/* Row 1: KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          label="Total Patients"
          value={fmt(s.total_patients)}
          sub={`+${s.new_patients_today} registered today`}
          accent="bg-blue-50"
          icon={
            <svg className="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          }
        />
        <KPICard
          label="OPD Visits Today"
          value={s.visits_today}
          sub={`${s.visits_completed_today} completed · ${s.visits_in_progress_today} active · ${opdRate}% rate`}
          accent="bg-violet-50"
          icon={
            <svg className="w-5 h-5 text-violet-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
          }
        />
        <KPICard
          label="Total Staff"
          value={s.total_staff}
          sub={staffSummary || 'No staff found'}
          accent="bg-emerald-50"
          icon={
            <svg className="w-5 h-5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
            </svg>
          }
        />
        <KPICard
          label="Revenue Today"
          value={fmtCurrency(s.revenue_today)}
          sub={`All-time: ${fmtCurrency(s.revenue_total)} · ${s.invoices_paid_today} paid today`}
          accent="bg-amber-50"
          icon={
            <svg className="w-5 h-5 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z" />
            </svg>
          }
        />
      </div>

      {/* Row 2: Service status panels */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">

        {/* Pharmacy */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
              </svg>
              <span className="text-sm font-semibold text-gray-700">Pharmacy</span>
            </div>
            <span className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full font-medium">{fmt(s.pharmacy_total)} total</span>
          </div>
          <div className="space-y-3">
            <div>
              <div className="flex justify-between text-xs text-gray-600">
                <span>Dispensed</span>
                <span className="font-semibold text-green-700">{s.pharmacy_dispensed}</span>
              </div>
              <ProgressBar value={s.pharmacy_dispensed} total={s.pharmacy_total} color="bg-green-500" />
            </div>
            <div>
              <div className="flex justify-between text-xs text-gray-600">
                <span>Pending / In Progress</span>
                <span className="font-semibold text-amber-700">{s.pharmacy_pending}</span>
              </div>
              <ProgressBar value={s.pharmacy_pending} total={s.pharmacy_total} color="bg-amber-400" />
            </div>
          </div>
          {s.pharmacy_total > 0 && (
            <p className="mt-3 text-xs text-gray-500 text-right">
              {s.pharmacy_total > 0 ? Math.round((s.pharmacy_dispensed / s.pharmacy_total) * 100) : 0}% fulfilment rate
            </p>
          )}
          {s.pharmacy_pending > 10 && (
            <p className="mt-2 text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-1.5">
              ⚠ {s.pharmacy_pending} prescriptions still awaiting dispensing
            </p>
          )}
        </div>

        {/* Lab */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
              </svg>
              <span className="text-sm font-semibold text-gray-700">Lab Orders</span>
            </div>
            <span className="text-xs bg-purple-50 text-purple-700 px-2 py-0.5 rounded-full font-medium">{fmt(s.lab_total)} total</span>
          </div>
          <div className="space-y-3">
            <div>
              <div className="flex justify-between text-xs text-gray-600">
                <span>Resulted</span>
                <span className="font-semibold text-green-700">{s.lab_resulted}</span>
              </div>
              <ProgressBar value={s.lab_resulted} total={s.lab_total} color="bg-green-500" />
            </div>
            <div>
              <div className="flex justify-between text-xs text-gray-600">
                <span>Pending</span>
                <span className="font-semibold text-amber-700">{s.lab_pending}</span>
              </div>
              <ProgressBar value={s.lab_pending} total={s.lab_total} color="bg-amber-400" />
            </div>
            <div>
              <div className="flex justify-between text-xs text-gray-600">
                <span>Rejected (needs recollection)</span>
                <span className="font-semibold text-red-600">{s.lab_rejected}</span>
              </div>
              <ProgressBar value={s.lab_rejected} total={s.lab_total} color="bg-red-400" />
            </div>
          </div>
          {s.lab_rejected > 0 && (
            <p className="mt-3 text-xs text-red-700 bg-red-50 rounded-lg px-3 py-1.5">
              ⚠ {s.lab_rejected} sample{s.lab_rejected > 1 ? 's' : ''} rejected — recollection needed
            </p>
          )}
        </div>

        {/* Billing */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
              </svg>
              <span className="text-sm font-semibold text-gray-700">Billing</span>
            </div>
            <span className="text-xs bg-green-50 text-green-700 px-2 py-0.5 rounded-full font-medium">{s.invoices_paid_today} paid today</span>
          </div>
          <div className="space-y-0.5">
            <div className="flex justify-between items-center py-2 border-b border-gray-50">
              <span className="text-xs text-gray-600">Revenue Today</span>
              <span className="text-sm font-bold text-green-700">{fmtCurrency(s.revenue_today)}</span>
            </div>
            <div className="flex justify-between items-center py-2 border-b border-gray-50">
              <span className="text-xs text-gray-600">All-time Revenue</span>
              <span className="text-sm font-bold text-gray-800">{fmtCurrency(s.revenue_total)}</span>
            </div>
            <div className="flex justify-between items-center py-2 border-b border-gray-50">
              <span className="text-xs text-gray-600">Invoices Paid Today</span>
              <span className="text-sm font-bold text-green-700">{s.invoices_paid_today}</span>
            </div>
            <div className="flex justify-between items-center py-2">
              <span className="text-xs text-gray-600">Pending Invoices (draft)</span>
              <span className={`text-sm font-bold ${s.invoices_draft > 0 ? 'text-amber-700' : 'text-gray-400'}`}>
                {s.invoices_draft}
              </span>
            </div>
          </div>
          {s.invoices_draft > 5 && (
            <p className="mt-2 text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-1.5">
              ⚠ {s.invoices_draft} invoices in draft — revenue not yet collected
            </p>
          )}
        </div>
      </div>

      {/* Row 3: Department performance table */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-5 py-3.5 border-b border-gray-100 flex items-center justify-between">
          <span className="text-sm font-semibold text-gray-700">Department Performance</span>
          <span className="text-xs text-gray-400">All-time visits</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50">
                <th className="px-5 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Department</th>
                <th className="px-5 py-2.5 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Total</th>
                <th className="px-5 py-2.5 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Completed</th>
                <th className="px-5 py-2.5 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">In Progress</th>
                <th className="px-5 py-2.5 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Rate</th>
                <th className="px-5 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide w-36">Visual</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {s.departments.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-5 py-8 text-center text-gray-400 text-sm">No departments configured</td>
                </tr>
              ) : s.departments.map(d => {
                const pct = d.total > 0 ? Math.round((d.completed / d.total) * 100) : 0
                const rateColor = pct >= 80 ? 'bg-green-100 text-green-700' : pct >= 50 ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700'
                const barColor = pct >= 80 ? 'bg-green-500' : pct >= 50 ? 'bg-amber-400' : 'bg-red-400'
                return (
                  <tr key={d.name} className="hover:bg-gray-50 transition-colors">
                    <td className="px-5 py-3 font-medium text-gray-900">{d.name}</td>
                    <td className="px-5 py-3 text-right text-gray-700">{d.total}</td>
                    <td className="px-5 py-3 text-right font-medium text-green-700">{d.completed}</td>
                    <td className="px-5 py-3 text-right text-amber-700">{d.in_progress}</td>
                    <td className="px-5 py-3 text-right">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${rateColor}`}>{pct}%</span>
                    </td>
                    <td className="px-5 py-3">
                      <div className="w-32 bg-gray-100 rounded-full h-2">
                        <div className={`h-2 rounded-full transition-all ${barColor}`} style={{ width: `${pct}%` }} />
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Row 4: Today's OPD + Appointments */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

        {/* OPD Today */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-semibold text-gray-700">Today's OPD</span>
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
              opdRate >= 70 ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'
            }`}>{opdRate}% completion</span>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="text-center p-3 rounded-lg bg-blue-50">
              <div className="text-2xl font-bold text-blue-700">{s.visits_today}</div>
              <div className="text-xs text-blue-600 mt-0.5">Total</div>
            </div>
            <div className="text-center p-3 rounded-lg bg-green-50">
              <div className="text-2xl font-bold text-green-700">{s.visits_completed_today}</div>
              <div className="text-xs text-green-600 mt-0.5">Completed</div>
            </div>
            <div className="text-center p-3 rounded-lg bg-amber-50">
              <div className="text-2xl font-bold text-amber-700">{s.visits_in_progress_today}</div>
              <div className="text-xs text-amber-600 mt-0.5">In Progress</div>
            </div>
          </div>
        </div>

        {/* Appointments Today */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-semibold text-gray-700">Today's Appointments</span>
            {apptCancelRate > 0 && (
              <span className="text-xs text-red-600 bg-red-50 px-2 py-0.5 rounded-full font-medium">
                {apptCancelRate}% cancelled
              </span>
            )}
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="text-center p-3 rounded-lg bg-blue-50">
              <div className="text-2xl font-bold text-blue-700">{s.appointments_today}</div>
              <div className="text-xs text-blue-600 mt-0.5">Scheduled</div>
            </div>
            <div className="text-center p-3 rounded-lg bg-green-50">
              <div className="text-2xl font-bold text-green-700">{s.appointments_completed_today}</div>
              <div className="text-xs text-green-600 mt-0.5">Completed</div>
            </div>
            <div className="text-center p-3 rounded-lg bg-red-50">
              <div className="text-2xl font-bold text-red-700">{s.appointments_cancelled_today}</div>
              <div className="text-xs text-red-600 mt-0.5">Cancelled</div>
            </div>
          </div>
          {apptCancelRate >= 20 && (
            <p className="mt-3 text-xs text-red-700 bg-red-50 rounded-lg px-3 py-1.5">
              ⚠ High cancellation rate today ({apptCancelRate}%) — consider follow-up with patients
            </p>
          )}
        </div>
      </div>

      {/* Row 5: Indent Expenditure */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2">
            <svg className="w-4 h-4 text-orange-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
            </svg>
            <span className="text-sm font-semibold text-gray-700">Indent Expenditure</span>
          </div>
          <div className="flex gap-1.5">
            {(['week', 'month', 'year'] as const).map(p => (
              <button
                key={p}
                onClick={() => setIndentPeriod(p)}
                className={`px-3 py-1 text-xs font-medium rounded-lg border transition-colors ${indentPeriod === p ? 'bg-orange-50 border-orange-400 text-orange-700' : 'border-gray-200 text-gray-500 hover:bg-gray-50'}`}
              >
                {p.charAt(0).toUpperCase() + p.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {indentStats ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-orange-50 rounded-xl p-4">
              <p className="text-xs font-semibold text-orange-600 uppercase tracking-wide">Total Indents</p>
              <p className="text-2xl font-bold text-orange-800 mt-1">{indentStats.total_indents}</p>
              <p className="text-xs text-orange-500 mt-0.5">since {indentStats.since}</p>
            </div>
            <div className="bg-red-50 rounded-xl p-4">
              <p className="text-xs font-semibold text-red-600 uppercase tracking-wide">Total Expenditure</p>
              <p className="text-2xl font-bold text-red-800 mt-1">
                {fmtCurrency(indentStats.total_expenditure)}
              </p>
              <p className="text-xs text-red-500 mt-0.5">amount entered by admin</p>
            </div>
            <div className="bg-green-50 rounded-xl p-4">
              <p className="text-xs font-semibold text-green-600 uppercase tracking-wide">Fulfilled</p>
              <p className="text-2xl font-bold text-green-800 mt-1">{indentStats.fulfilled_count}</p>
              <p className="text-xs text-green-500 mt-0.5">{fmtCurrency(indentStats.fulfilled_amount)} value</p>
            </div>
            <div className="bg-yellow-50 rounded-xl p-4">
              <p className="text-xs font-semibold text-yellow-600 uppercase tracking-wide">Pending / Approved</p>
              <p className="text-2xl font-bold text-yellow-800 mt-1">
                {indentStats.pending_count + indentStats.approved_count}
              </p>
              <p className="text-xs text-yellow-500 mt-0.5">{indentStats.pending_count} pending · {indentStats.approved_count} approved</p>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => <div key={i} className="h-24 bg-gray-100 rounded-xl animate-pulse" />)}
          </div>
        )}
      </div>

      {/* Row 6: Public display board credential */}
      <DisplayBoardCard />
    </div>
  )
}
