/**
 * Hospital Admin Nurse Roster management — daily/weekly views, create/edit/
 * deactivate, attendance, and substitution. Hospital Admin owns this screen;
 * Nurse gets a separate read-only page (see features/nurse/RosterPage.tsx).
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Calendar, CalendarDays, ChevronLeft, ChevronRight, History, Pencil, Plus, Search, XCircle } from 'lucide-react'
import { nurseRosterService, type NurseRoster, type NurseRosterCreateInput } from '@/services/nurseRosterService'
import { departmentService, doctorService, userService } from '@/services/clinicalService'

type ViewMode = 'daily' | 'weekly'
type ToastType = 'success' | 'error'

const SHIFTS: Array<NurseRoster['shift']> = ['morning', 'afternoon', 'night']
const SHIFT_LABELS: Record<string, string> = { morning: 'Morning', afternoon: 'Afternoon', night: 'Night' }

function toIso(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function startOfWeek(d: Date): Date {
  const copy = new Date(d)
  const day = copy.getDay() // 0=Sun
  copy.setDate(copy.getDate() - day)
  return copy
}

function formatShortDate(iso: string): string {
  return new Date(iso + 'T00:00:00').toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
}

interface FormState {
  id?: string
  user_id: string
  roster_date: string
  shift: NurseRoster['shift']
  department_id: string
  room: string
  assigned_doctor_id: string
  substitute_user_id: string
  substitution_reason: string
}

function emptyForm(date: string): FormState {
  return {
    user_id: '', roster_date: date, shift: 'morning', department_id: '',
    room: '', assigned_doctor_id: '', substitute_user_id: '', substitution_reason: '',
  }
}

export default function NurseRosterAdminPage() {
  const qc = useQueryClient()
  const [viewMode, setViewMode] = useState<ViewMode>('daily')
  const [anchorDate, setAnchorDate] = useState(() => toIso(new Date()))
  const [filterNurse, setFilterNurse] = useState('')
  const [filterDepartment, setFilterDepartment] = useState('')
  const [filterShift, setFilterShift] = useState('')
  const [form, setForm] = useState<FormState | null>(null)
  const [toast, setToast] = useState<{ message: string; type: ToastType } | null>(null)
  const [confirmDeactivate, setConfirmDeactivate] = useState<NurseRoster | null>(null)
  const [deactivateReason, setDeactivateReason] = useState('')

  const weekStart = useMemo(() => toIso(startOfWeek(new Date(anchorDate + 'T00:00:00'))), [anchorDate])
  const weekEnd = useMemo(() => {
    const d = new Date(weekStart + 'T00:00:00')
    d.setDate(d.getDate() + 6)
    return toIso(d)
  }, [weekStart])

  const listParams = viewMode === 'daily'
    ? { roster_date: anchorDate }
    : { date_from: weekStart, date_to: weekEnd }

  const roster = useQuery({
    queryKey: ['nurse-roster', 'admin', viewMode, anchorDate],
    queryFn: () => nurseRosterService.list(listParams),
  })
  const nurses = useQuery({ queryKey: ['users', 'nurse'], queryFn: () => userService.list({ role: 'nurse' }) })
  const departments = useQuery({ queryKey: ['departments'], queryFn: () => departmentService.list() })
  const doctors = useQuery({ queryKey: ['doctors'], queryFn: () => doctorService.list() })
  const audit = useQuery({ queryKey: ['nurse-roster', 'audit'], queryFn: () => nurseRosterService.auditHistory() })

  const showToast = (message: string, type: ToastType = 'success') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3500)
  }

  const invalidate = () => qc.invalidateQueries({ queryKey: ['nurse-roster', 'admin'] })

  const createMutation = useMutation({
    mutationFn: (data: NurseRosterCreateInput) => nurseRosterService.create(data),
    onSuccess: () => { invalidate(); setForm(null); showToast('Roster entry created') },
    onError: (err: any) => showToast(err?.response?.data?.detail ?? 'Failed to create roster entry', 'error'),
  })
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<NurseRoster> & { reason?: string } }) => nurseRosterService.update(id, data),
    onSuccess: () => { invalidate(); setForm(null); setConfirmDeactivate(null); setDeactivateReason(''); showToast('Roster entry updated') },
    onError: (err: any) => showToast(err?.response?.data?.detail ?? 'Failed to update roster entry', 'error'),
  })

  const rows = (roster.data ?? []).filter(row => {
    if (filterDepartment && row.department_id !== filterDepartment) return false
    if (filterShift && row.shift !== filterShift) return false
    if (filterNurse && !(row.nurse_name ?? '').toLowerCase().includes(filterNurse.toLowerCase())) return false
    return true
  })

  const grouped = useMemo(() => {
    const map = new Map<string, NurseRoster[]>()
    for (const row of rows) {
      const list = map.get(row.roster_date) ?? []
      list.push(row)
      map.set(row.roster_date, list)
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [rows])

  const shiftDate = (deltaDays: number) => {
    const d = new Date(anchorDate + 'T00:00:00')
    d.setDate(d.getDate() + deltaDays * (viewMode === 'weekly' ? 7 : 1))
    setAnchorDate(toIso(d))
  }

  const openCreate = () => setForm(emptyForm(anchorDate))
  const openEdit = (row: NurseRoster) => setForm({
    id: row.id, user_id: row.user_id, roster_date: row.roster_date, shift: row.shift,
    department_id: row.department_id, room: row.room ?? '', assigned_doctor_id: row.assigned_doctor_id ?? '',
    substitute_user_id: row.substitute_user_id ?? '', substitution_reason: row.substitution_reason ?? '',
  })

  const submitForm = () => {
    if (!form) return
    if (!form.user_id || !form.roster_date || !form.department_id) {
      showToast('Nurse, date, and department are required', 'error')
      return
    }
    if (form.substitute_user_id && !form.substitution_reason.trim()) {
      showToast('Substitution reason is required when a substitute nurse is selected', 'error')
      return
    }
    const payload = {
      user_id: form.user_id,
      roster_date: form.roster_date,
      shift: form.shift,
      department_id: form.department_id,
      room: form.room || undefined,
      assigned_doctor_id: form.assigned_doctor_id || undefined,
      substitute_user_id: form.substitute_user_id || undefined,
      substitution_reason: form.substitution_reason || undefined,
    }
    if (form.id) {
      updateMutation.mutate({ id: form.id, data: payload })
    } else {
      createMutation.mutate(payload as NurseRosterCreateInput)
    }
  }

  const toggleAttendance = (row: NurseRoster) => {
    updateMutation.mutate({ id: row.id, data: { is_present: !row.is_present } })
  }

  const confirmDeactivateSubmit = () => {
    if (!confirmDeactivate) return
    if (!deactivateReason.trim()) {
      showToast('Deactivation reason is required', 'error')
      return
    }
    updateMutation.mutate({ id: confirmDeactivate.id, data: { is_active: false, reason: deactivateReason.trim() } })
  }

  const isSaving = createMutation.isPending || updateMutation.isPending

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Nurse Roster</h1>
          <p className="text-sm text-gray-500 mt-1">Create, edit, and manage duty assignments and attendance</p>
        </div>
        <button
          type="button"
          onClick={openCreate}
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90"
        >
          <Plus className="h-4 w-4" aria-hidden="true" /> New Roster Entry
        </button>
      </div>

      <section className="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <div className="flex items-center gap-2 border-b border-gray-200 px-5 py-3">
          <History className="h-4 w-4 text-gray-500" aria-hidden="true" />
          <h2 className="font-semibold text-gray-900">Roster audit history</h2>
        </div>
        {audit.isLoading ? <p className="p-5 text-sm text-gray-500">Loading audit history...</p>
          : audit.isError ? <p role="alert" className="p-5 text-sm text-red-600">Could not load roster audit history.</p>
          : audit.data?.length ? <div className="divide-y divide-gray-100">{audit.data.map(entry => <article key={entry.id} className="grid gap-1 px-5 py-3 text-sm sm:grid-cols-[140px_1fr_auto]"><b>{entry.action}</b><span className="text-gray-600">{entry.reason || 'No reason recorded'}</span><time className="text-xs text-gray-500">{new Date(entry.timestamp).toLocaleString()}</time></article>)}</div>
          : <p className="p-5 text-sm text-gray-500">No roster audit entries.</p>}
      </section>

      <div className="flex flex-wrap items-center gap-3 bg-white border border-gray-200 rounded-xl p-4">
        <div className="inline-flex rounded-lg border border-gray-300 overflow-hidden">
          <button
            type="button"
            onClick={() => setViewMode('daily')}
            className={`px-3 py-2 text-sm font-medium inline-flex items-center gap-1.5 ${viewMode === 'daily' ? 'bg-primary text-white' : 'bg-white text-gray-600'}`}
          >
            <Calendar className="h-4 w-4" aria-hidden="true" /> Daily
          </button>
          <button
            type="button"
            onClick={() => setViewMode('weekly')}
            className={`px-3 py-2 text-sm font-medium inline-flex items-center gap-1.5 border-l border-gray-300 ${viewMode === 'weekly' ? 'bg-primary text-white' : 'bg-white text-gray-600'}`}
          >
            <CalendarDays className="h-4 w-4" aria-hidden="true" /> Weekly
          </button>
        </div>

        <div className="inline-flex items-center gap-1">
          <button type="button" onClick={() => shiftDate(-1)} aria-label="Previous" className="p-2 rounded-lg hover:bg-gray-100">
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          </button>
          <input
            type="date"
            value={anchorDate}
            onChange={e => setAnchorDate(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
          />
          <button type="button" onClick={() => shiftDate(1)} aria-label="Next" className="p-2 rounded-lg hover:bg-gray-100">
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </button>
          {viewMode === 'weekly' && <span className="text-xs text-gray-500 ml-1">{weekStart} – {weekEnd}</span>}
        </div>

        <div className="relative">
          <Search className="h-4 w-4 text-gray-400 absolute left-2.5 top-2.5" aria-hidden="true" />
          <input
            type="text"
            placeholder="Search nurse…"
            value={filterNurse}
            onChange={e => setFilterNurse(e.target.value)}
            className="pl-8 pr-3 py-2 border border-gray-300 rounded-lg text-sm"
          />
        </div>
        <select value={filterDepartment} onChange={e => setFilterDepartment(e.target.value)} className="border border-gray-300 rounded-lg px-3 py-2 text-sm">
          <option value="">All departments</option>
          {(departments.data ?? []).map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <select value={filterShift} onChange={e => setFilterShift(e.target.value)} className="border border-gray-300 rounded-lg px-3 py-2 text-sm">
          <option value="">All shifts</option>
          {SHIFTS.map(s => <option key={s} value={s}>{SHIFT_LABELS[s]}</option>)}
        </select>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        {roster.isLoading ? (
          <div className="p-8 text-sm text-gray-500" role="status">Loading roster…</div>
        ) : roster.isError ? (
          <div className="p-8 text-sm text-red-600" role="alert">Could not load the roster. Please try again.</div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-sm text-gray-500">No roster entries match the current filters.</div>
        ) : (
          <div className="divide-y divide-gray-100">
            {grouped.map(([dateIso, entries]) => (
              <div key={dateIso}>
                {viewMode === 'weekly' && (
                  <div className="px-5 py-2 bg-gray-50 text-xs font-semibold uppercase tracking-wide text-gray-500">
                    {formatShortDate(dateIso)}
                  </div>
                )}
                {entries.map(row => (
                  <div key={row.id} className="px-5 py-4 flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 first:border-t-0">
                    <div className="min-w-[220px]">
                      <p className="font-medium text-gray-900">{row.nurse_name || 'Nurse'}</p>
                      <p className="text-sm text-gray-500">
                        {row.department_name || 'Department'} · {SHIFT_LABELS[row.shift] || row.shift} · {row.room || 'Room not assigned'}
                        {row.doctor_name ? ` · Dr. ${row.doctor_name}` : ''}
                      </p>
                      {row.substitute_name && (
                        <p className="text-xs text-amber-700 mt-1">Substitute: {row.substitute_name} — {row.substitution_reason}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => toggleAttendance(row)}
                        className={`px-3 py-2 rounded-lg text-sm font-medium ${row.is_present ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}
                      >
                        {row.is_present ? 'Present' : 'Mark present'}
                      </button>
                      <button type="button" onClick={() => openEdit(row)} aria-label="Edit" className="p-2 rounded-lg hover:bg-gray-100">
                        <Pencil className="h-4 w-4 text-gray-500" aria-hidden="true" />
                      </button>
                      <button type="button" onClick={() => setConfirmDeactivate(row)} aria-label="Deactivate" className="p-2 rounded-lg hover:bg-red-50">
                        <XCircle className="h-4 w-4 text-red-500" aria-hidden="true" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>

      {form && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl p-6 w-full max-w-lg space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">{form.id ? 'Edit Roster Entry' : 'New Roster Entry'}</h2>
            <div className="grid grid-cols-2 gap-4">
              <label className="text-sm font-medium text-gray-700 col-span-2">Nurse
                <select value={form.user_id} onChange={e => setForm({ ...form, user_id: e.target.value })} className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2">
                  <option value="">Select nurse…</option>
                  {(nurses.data ?? []).map((n: any) => <option key={n.id} value={n.id}>{n.full_name}</option>)}
                </select>
              </label>
              <label className="text-sm font-medium text-gray-700">Date
                <input type="date" value={form.roster_date} onChange={e => setForm({ ...form, roster_date: e.target.value })} className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2" />
              </label>
              <label className="text-sm font-medium text-gray-700">Shift
                <select value={form.shift} onChange={e => setForm({ ...form, shift: e.target.value as NurseRoster['shift'] })} className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2">
                  {SHIFTS.map(s => <option key={s} value={s}>{SHIFT_LABELS[s]}</option>)}
                </select>
              </label>
              <label className="text-sm font-medium text-gray-700">Department
                <select value={form.department_id} onChange={e => setForm({ ...form, department_id: e.target.value })} className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2">
                  <option value="">Select department…</option>
                  {(departments.data ?? []).map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </label>
              <label className="text-sm font-medium text-gray-700">Room
                <input type="text" value={form.room} onChange={e => setForm({ ...form, room: e.target.value })} className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2" />
              </label>
              <label className="text-sm font-medium text-gray-700 col-span-2">Assigned Doctor (optional)
                <select value={form.assigned_doctor_id} onChange={e => setForm({ ...form, assigned_doctor_id: e.target.value })} className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2">
                  <option value="">None</option>
                  {(doctors.data ?? []).map((d: any) => <option key={d.id} value={d.id}>{d.full_name}</option>)}
                </select>
              </label>
              <label className="text-sm font-medium text-gray-700 col-span-2">Substitute Nurse (optional)
                <select value={form.substitute_user_id} onChange={e => setForm({ ...form, substitute_user_id: e.target.value })} className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2">
                  <option value="">None</option>
                  {(nurses.data ?? []).filter((n: any) => n.id !== form.user_id).map((n: any) => <option key={n.id} value={n.id}>{n.full_name}</option>)}
                </select>
              </label>
              {form.substitute_user_id && (
                <label className="text-sm font-medium text-gray-700 col-span-2">Substitution reason (required)
                  <input type="text" value={form.substitution_reason} onChange={e => setForm({ ...form, substitution_reason: e.target.value })} className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2" />
                </label>
              )}
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={() => setForm(null)} className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100">Cancel</button>
              <button type="button" onClick={submitForm} disabled={isSaving} className="px-4 py-2 rounded-lg text-sm font-medium bg-primary text-white hover:bg-primary/90 disabled:opacity-50">
                {isSaving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmDeactivate && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl p-6 w-full max-w-sm space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">Deactivate roster entry?</h2>
            <p className="text-sm text-gray-600">
              This removes {confirmDeactivate.nurse_name || 'this nurse'}'s assignment for {formatShortDate(confirmDeactivate.roster_date)} ({SHIFT_LABELS[confirmDeactivate.shift]}).
            </p>
            <label className="text-sm font-medium text-gray-700 block">Reason (required)
              <input type="text" value={deactivateReason} onChange={e => setDeactivateReason(e.target.value)} className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2" />
            </label>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => { setConfirmDeactivate(null); setDeactivateReason('') }} className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100">Cancel</button>
              <button type="button" onClick={confirmDeactivateSubmit} disabled={isSaving || !deactivateReason.trim()} className="px-4 py-2 rounded-lg text-sm font-medium bg-red-600 text-white hover:bg-red-700 disabled:opacity-50">
                {isSaving ? 'Deactivating…' : 'Deactivate'}
              </button>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div role="status" className={`fixed bottom-6 right-6 z-50 rounded-lg px-4 py-3 text-sm font-medium text-white shadow-lg ${toast.type === 'success' ? 'bg-green-600' : 'bg-red-600'}`}>
          {toast.message}
        </div>
      )}
    </div>
  )
}
