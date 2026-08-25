import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import { doctorService } from '@/services/clinicalService'
import { doctorScheduleService, type DoctorSchedule } from '@/services/doctorScheduleService'

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const EMPTY = { start_time: '09:00', end_time: '13:00', slot_duration_minutes: 15, capacity: 1, room: '', appointment_type: 'consultation', notes: '' }

type Draft = typeof EMPTY

export default function DoctorSchedulesPage() {
  const [searchParams] = useSearchParams()
  const qc = useQueryClient()
  const [doctorId, setDoctorId] = useState(searchParams.get('doctor_id') ?? '')
  const [date, setDate] = useState(format(new Date(), 'yyyy-MM-dd'))
  const [drafts, setDrafts] = useState<Record<number, Draft>>({})
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [showExceptionForm, setShowExceptionForm] = useState(false)
  const [exceptionType, setExceptionType] = useState<'leave' | 'holiday' | 'block'>('block')
  const [exceptionStart, setExceptionStart] = useState(`${format(new Date(), 'yyyy-MM-dd')}T13:00`)
  const [exceptionEnd, setExceptionEnd] = useState(`${format(new Date(), 'yyyy-MM-dd')}T14:00`)
  const [exceptionReason, setExceptionReason] = useState('')

  const { data: doctors = [] } = useQuery({ queryKey: ['doctors'], queryFn: () => doctorService.list() })
  const { data: schedules = [], isLoading } = useQuery({
    queryKey: ['doctor-schedules', doctorId],
    queryFn: () => doctorScheduleService.listDoctorSchedules({ doctor_id: doctorId, include_inactive: true }),
    enabled: !!doctorId,
  })
  const { data: availabilityDays = [] } = useQuery({
    queryKey: ['doctor-availability', doctorId, date],
    queryFn: () => doctorScheduleService.getDoctorAvailability(doctorId, date),
    enabled: !!doctorId && !!date,
  })
  const { data: exceptions = [] } = useQuery({
    queryKey: ['doctor-exceptions', doctorId],
    queryFn: () => doctorScheduleService.listScheduleExceptions(doctorId),
    enabled: !!doctorId,
  })

  const save = useMutation({
    mutationFn: ({ weekday, draft }: { weekday: number; draft: Draft }) => doctorScheduleService.createDoctorSchedule({ ...draft, doctor_id: doctorId, department_id: doctors.find(d => d.id === doctorId)?.department_id ?? null, weekday, effective_from: null, effective_to: null, is_active: true }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['doctor-schedules', doctorId] }); setMessage('Schedule session saved'); setError('') },
    onError: (e: any) => setError(e?.response?.data?.detail ?? 'Could not save schedule'),
  })
  const deactivate = useMutation({
    mutationFn: doctorScheduleService.deactivateDoctorSchedule,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['doctor-schedules', doctorId] }),
  })
  const addException = useMutation({
    mutationFn: () => doctorScheduleService.createScheduleException(doctorId, { exception_type: exceptionType, start_datetime: exceptionStart, end_datetime: exceptionEnd, reason: exceptionReason.trim() || null, is_active: true }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['doctor-exceptions', doctorId] }); setShowExceptionForm(false); setExceptionReason('') },
  })

  const draftFor = (weekday: number) => drafts[weekday] ?? EMPTY
  const updateDraft = (weekday: number, key: keyof Draft, value: string | number) => setDrafts(current => ({ ...current, [weekday]: { ...draftFor(weekday), [key]: value } }))
  const copyMonday = () => setDrafts(Object.fromEntries(DAYS.map((_, day) => [day, { ...draftFor(0) }])))

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div><h1 className="text-xl font-semibold text-gray-900">Doctor Schedules</h1><p className="text-sm text-gray-500 mt-1">Configure recurring consultation sessions and preview valid availability.</p></div>
        <select value={doctorId} onChange={e => setDoctorId(e.target.value)} className="border border-gray-300 rounded-lg px-3 py-2 text-sm min-w-64">
          <option value="">Select doctor</option>{doctors.map(d => <option key={d.id} value={d.id}>{d.full_name} · {d.specialization}</option>)}
        </select>
      </div>
      {!doctorId ? <div className="bg-white border border-dashed border-gray-300 rounded-xl p-12 text-center text-sm text-gray-500">Select a doctor to manage their schedule.</div> : <>
        {(message || error) && <p className={`text-sm rounded-lg px-3 py-2 ${error ? 'text-red-700 bg-red-50' : 'text-green-700 bg-green-50'}`}>{error || message}</p>}
        <section className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200"><h2 className="font-semibold text-gray-900">Weekly sessions</h2><button type="button" onClick={copyMonday} className="text-sm text-primary hover:underline">Copy Monday to all days</button></div>
          <div className="divide-y divide-gray-100">{DAYS.map((day, weekday) => { const draft = draftFor(weekday); return <div key={day} className="p-4 grid grid-cols-[120px_1fr_auto] gap-4 items-end"><div className="text-sm font-medium text-gray-800">{day}</div><div className="grid grid-cols-2 md:grid-cols-6 gap-2">
            <label className="text-xs text-gray-500">Start<input type="time" value={draft.start_time} onChange={e => updateDraft(weekday, 'start_time', e.target.value)} className="block w-full border rounded px-2 py-1.5 text-sm" /></label>
            <label className="text-xs text-gray-500">End<input type="time" value={draft.end_time} onChange={e => updateDraft(weekday, 'end_time', e.target.value)} className="block w-full border rounded px-2 py-1.5 text-sm" /></label>
            <label className="text-xs text-gray-500">Minutes<input type="number" min="5" max="240" value={draft.slot_duration_minutes} onChange={e => updateDraft(weekday, 'slot_duration_minutes', Number(e.target.value))} className="block w-full border rounded px-2 py-1.5 text-sm" /></label>
            <label className="text-xs text-gray-500">Capacity<input type="number" min="1" max="100" value={draft.capacity} onChange={e => updateDraft(weekday, 'capacity', Number(e.target.value))} className="block w-full border rounded px-2 py-1.5 text-sm" /></label>
            <label className="text-xs text-gray-500">Room<input value={draft.room} onChange={e => updateDraft(weekday, 'room', e.target.value)} className="block w-full border rounded px-2 py-1.5 text-sm" /></label>
            <label className="text-xs text-gray-500">Type<select value={draft.appointment_type} onChange={e => updateDraft(weekday, 'appointment_type', e.target.value)} className="block w-full border rounded px-2 py-1.5 text-sm"><option>consultation</option><option>follow-up</option><option>teleconsultation</option></select></label>
          </div><button type="button" onClick={() => save.mutate({ weekday, draft })} disabled={save.isPending} className="bg-primary text-white rounded-lg px-3 py-2 text-xs font-medium disabled:opacity-50">Save session</button></div> })}</div>
        </section>
        <section className="bg-white border border-gray-200 rounded-xl p-5"><h2 className="font-semibold text-gray-900 mb-3">Configured sessions</h2>{isLoading ? <p className="text-sm text-gray-400">Loading…</p> : schedules.length === 0 ? <p className="text-sm text-gray-500">No schedule configured for this doctor.</p> : <div className="space-y-2">{schedules.map((schedule: DoctorSchedule) => <div key={schedule.id} className="flex items-center justify-between border rounded-lg px-3 py-2 text-sm"><span>{DAYS[schedule.weekday]} · {schedule.start_time.slice(0, 5)}–{schedule.end_time.slice(0, 5)} · {schedule.capacity} per slot · {schedule.room || 'No room'}{!schedule.is_active && ' · inactive'}</span>{schedule.is_active && <button type="button" onClick={() => deactivate.mutate(schedule.id)} className="text-red-600 text-xs">Deactivate</button>}</div>)}</div>}</section>
        <section className="bg-white border border-gray-200 rounded-xl p-5"><div className="flex items-center justify-between mb-3"><div><h2 className="font-semibold text-gray-900">Availability preview</h2><p className="text-xs text-gray-500">Timezone: {availabilityDays[0]?.timezone ?? 'Asia/Kolkata'}</p></div><input type="date" value={date} onChange={e => setDate(e.target.value)} className="border rounded px-2 py-1.5 text-sm" /></div>{availabilityDays[0]?.slots.length ? <div className="grid grid-cols-3 md:grid-cols-8 gap-2">{availabilityDays[0].slots.map(slot => <div key={slot.slot_time} className={`rounded border px-2 py-2 text-center text-xs ${slot.is_available ? 'bg-green-50 text-green-700 border-green-200' : 'bg-gray-50 text-gray-400 border-gray-200'}`}><div>{new Date(slot.slot_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div><div>{slot.booked_count}/{slot.capacity}</div></div>)}</div> : <p className="text-sm text-gray-500">No consultation schedule is configured for this doctor on the selected date.</p>}</section>
        <section className="bg-white border border-gray-200 rounded-xl p-5"><div className="flex items-center justify-between mb-3"><h2 className="font-semibold text-gray-900">Leave and blocked periods</h2><button type="button" onClick={() => setShowExceptionForm(true)} className="bg-amber-600 text-white rounded-lg px-3 py-2 text-xs font-medium">Add exception</button></div>{showExceptionForm && <div className="border border-amber-200 bg-amber-50 rounded-lg p-4 mb-4 space-y-3"><div className="grid grid-cols-3 gap-2"><label className="text-xs text-gray-600">Type<select value={exceptionType} onChange={e => setExceptionType(e.target.value as typeof exceptionType)} className="block w-full border rounded px-2 py-1.5 text-sm"><option value="leave">Leave</option><option value="holiday">Holiday</option><option value="block">Blocked period</option></select></label><label className="text-xs text-gray-600">Starts<input type="datetime-local" value={exceptionStart} onChange={e => setExceptionStart(e.target.value)} className="block w-full border rounded px-2 py-1.5 text-sm" /></label><label className="text-xs text-gray-600">Ends<input type="datetime-local" value={exceptionEnd} onChange={e => setExceptionEnd(e.target.value)} className="block w-full border rounded px-2 py-1.5 text-sm" /></label></div><input value={exceptionReason} onChange={e => setExceptionReason(e.target.value)} maxLength={500} placeholder="Reason (optional)" className="w-full border rounded px-3 py-2 text-sm" /><div className="flex justify-end gap-2"><button type="button" onClick={() => setShowExceptionForm(false)} className="border border-gray-300 rounded px-3 py-2 text-xs">Cancel</button><button type="button" disabled={addException.isPending || exceptionStart >= exceptionEnd} onClick={() => addException.mutate()} className="bg-amber-600 text-white rounded px-3 py-2 text-xs disabled:opacity-50">Save exception</button></div></div>}{exceptions.length === 0 ? <p className="text-sm text-gray-500">No active exceptions.</p> : <div className="space-y-2">{exceptions.filter(e => e.is_active).map(e => <div key={e.id} className="text-sm border rounded px-3 py-2">{e.exception_type}: {new Date(e.start_datetime).toLocaleString()}–{new Date(e.end_datetime).toLocaleString()} · {e.reason || 'No reason'}</div>)}</div>}</section>
      </>}
    </div>
  )
}
