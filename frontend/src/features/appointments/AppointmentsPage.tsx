/**
 * Appointments Page — day-view calendar, slot booking, check-in
 *
 * Layout:
 *   Top: date picker + doctor filter + "Book" button
 *   Left: list of today's appointments with status badges + check-in / cancel actions
 *   Right: slot availability grid for selected doctor
 */
import { useState, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { format, addDays, subDays, parseISO } from 'date-fns'
import { appointmentService, doctorService, departmentService, billingService } from '@/services/clinicalService'
import { patientService } from '@/services/patientService'
import { useWebSocket } from '@/hooks/useWebSocket'
import { RegisterPatientModal } from '@/components/shared/RegisterPatientModal'
import type { Appointment, AppointmentSlot, Doctor, Patient, Department } from '@/types/common'

// ── Helpers ───────────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  scheduled:  'bg-blue-100 text-blue-700',
  confirmed:  'bg-indigo-100 text-indigo-700',
  checked_in: 'bg-yellow-100 text-yellow-700',
  completed:  'bg-green-100 text-green-700',
  cancelled:  'bg-red-100 text-red-600',
  no_show:    'bg-gray-100 text-gray-500',
}

const StatusBadge = ({ status }: { status: string }) => (
  <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium capitalize ${STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-500'}`}>
    {status.replace('_', ' ')}
  </span>
)

const inputCls = 'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary'

// ── Book Modal ─────────────────────────────────────────────────────────────────

/** Convert 12-hour clock to 24-hour value */
function to24h(h12: number, ampm: 'AM' | 'PM'): number {
  if (ampm === 'AM') return h12 === 12 ? 0 : h12
  return h12 === 12 ? 12 : h12 + 12
}

const bookSchema = z.object({
  patient_id: z.string().min(1, 'Select a patient'),
  doctor_id:  z.string().min(1, 'Select a doctor'),
  slot_time:  z.string().min(1, 'Select a slot'),
  notes:      z.string().optional(),
  type:       z.enum(['walkin', 'phone', 'online']),
})
type BookForm = z.infer<typeof bookSchema>

// ─── Check-In Confirm Modal ────────────────────────────────────────────────────
function ConfirmRow({ label, value, sub, highlight }: { label: string; value: string; sub?: string; highlight?: 'red' | 'yellow' | 'green' | 'blue' }) {
  const valueColor = highlight === 'red' ? 'text-red-600' : highlight === 'yellow' ? 'text-yellow-700' : highlight === 'green' ? 'text-green-700' : highlight === 'blue' ? 'text-blue-700' : 'text-gray-900'
  return (
    <div className="flex items-start justify-between px-4 py-2.5">
      <span className="text-xs text-gray-500 w-32 flex-shrink-0">{label}</span>
      <span className={`text-xs font-medium text-right ${valueColor}`}>
        {value}
        {sub && <span className="block text-gray-400 font-normal">{sub}</span>}
      </span>
    </div>
  )
}

function CheckInConfirmModal({
  appt,
  doctor,
  onClose,
}: {
  appt: Appointment
  doctor: Doctor | undefined
  onClose: () => void
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [waiveFee, setWaiveFee] = useState(false)
  const [payMode, setPayMode] = useState<'cash' | 'online'>('cash')
  const [payError, setPayError] = useState('')

  const fee = doctor?.consultation_fee ?? 0

  // Fetch last visit history for follow-up check
  const { data: history = [] } = useQuery({
    queryKey: ['patient-last-visit', appt.patient_id],
    queryFn: () => patientService.getHistory(appt.patient_id),
    staleTime: 60_000,
  })

  const today = new Date(); today.setHours(0, 0, 0, 0)
  const pastVisits = (history as any[]).filter(
    (h: any) => !['registered', 'vitals_recorded', 'vitals_done', 'in_consultation', 'pre_billing'].includes(h.status)
  )
  const lastVisit = pastVisits.length > 0 ? new Date(pastVisits[0].visit_date) : null
  const daysDiff = lastVisit ? Math.floor((today.getTime() - new Date(lastVisit).setHours(0, 0, 0, 0)) / 86400000) : null
  const isFollowUp = daysDiff !== null && daysDiff <= 7
  const lastVisitLabel = lastVisit
    ? `${lastVisit.toLocaleDateString('en-GB')} (${daysDiff === 0 ? 'today' : daysDiff === 1 ? '1 day ago' : `${daysDiff} days ago`})`
    : null

  const admitCash = useMutation({
    mutationFn: (invoiceId: string) => billingService.admitPatient(invoiceId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['appointments'] })
      qc.invalidateQueries({ queryKey: ['queue'] })
      onClose()
      navigate('/queue?tab=consultation')
    },
    onError: () => setPayError('Cash collection failed — try again'),
  })

  const checkinMut = useMutation({
    mutationFn: () => appointmentService.checkin(appt.id, waiveFee),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['appointments'] })
      qc.invalidateQueries({ queryKey: ['queue'] })
      if (!res.needs_payment || waiveFee) {
        // No fee / waived — straight to queue
        onClose()
        navigate('/queue?tab=consultation')
      } else if (payMode === 'cash' && res.invoice_id) {
        // Cash: immediately admit
        admitCash.mutate(res.invoice_id)
      } else {
        // Online: POS kiosk already triggered by backend — go to queue
        onClose()
        navigate('/queue?tab=consultation')
      }
    },
  })

  const isPending = checkinMut.isPending || admitCash.isPending
  const isError = checkinMut.isError || admitCash.isError

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md mx-4">
        <div className="p-5 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900">Confirm Check-In</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl leading-none">×</button>
        </div>

        <div className="p-5 space-y-4">
          {/* Summary */}
          <div className="bg-gray-50 rounded-xl divide-y divide-gray-200 border border-gray-200">
            <ConfirmRow label="Patient" value={appt.patient_name ?? '—'} sub={appt.patient_uhid} />
            <ConfirmRow label="Doctor" value={doctor ? `Dr. ${doctor.full_name}` : '—'} sub={doctor?.specialization} />
            <ConfirmRow label="Slot" value={format(parseISO(appt.slot_time), 'dd MMM yyyy, HH:mm')} />
            <ConfirmRow label="Type" value={appt.type === 'phone' ? 'Phone Booking' : appt.type === 'online' ? 'Online Booking' : 'Walk-in'} />
            {lastVisitLabel && (
              <ConfirmRow label="Last Visit" value={lastVisitLabel} highlight={isFollowUp ? 'green' : undefined} />
            )}
            {fee > 0 && (
              <ConfirmRow
                label="Consultation Fee"
                value={waiveFee ? 'Free (follow-up)' : `₹${fee}`}
                highlight={waiveFee ? 'green' : 'blue'}
              />
            )}
          </div>

          {/* Follow-up waiver */}
          {fee > 0 && isFollowUp && (
            <label className="flex items-start gap-3 bg-green-50 border border-green-200 rounded-xl px-4 py-3 cursor-pointer">
              <input
                type="checkbox"
                checked={waiveFee}
                onChange={e => setWaiveFee(e.target.checked)}
                className="mt-0.5 accent-green-600 w-4 h-4"
              />
              <div>
                <p className="text-sm font-medium text-green-800">Waive consultation fee</p>
                <p className="text-xs text-green-700 mt-0.5">
                  Last visit was {daysDiff} {daysDiff === 1 ? 'day' : 'days'} ago — follow-up within 7 days is free.
                </p>
              </div>
            </label>
          )}

          {/* Payment mode toggle */}
          {fee > 0 && !waiveFee && (
            <div className="space-y-2">
              <p className="text-xs font-medium text-gray-700">Payment Method</p>
              <div className="flex rounded-lg border border-gray-200 overflow-hidden">
                <button
                  type="button"
                  onClick={() => setPayMode('cash')}
                  className={`flex-1 py-2.5 text-sm font-medium transition-colors ${
                    payMode === 'cash'
                      ? 'bg-green-600 text-white'
                      : 'bg-white text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  💵 Cash
                </button>
                <button
                  type="button"
                  onClick={() => setPayMode('online')}
                  className={`flex-1 py-2.5 text-sm font-medium border-l border-gray-200 transition-colors ${
                    payMode === 'online'
                      ? 'bg-blue-600 text-white'
                      : 'bg-white text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  📲 Online (Razorpay)
                </button>
              </div>
              {payMode === 'cash' && (
                <p className="text-xs text-green-700 bg-green-50 rounded-lg px-3 py-2">
                  Reception will collect <strong>₹{fee}</strong> cash and admit the patient.
                </p>
              )}
              {payMode === 'online' && (
                <p className="text-xs text-blue-700 bg-blue-50 rounded-lg px-3 py-2">
                  Payment request will be sent to the POS kiosk for <strong>₹{fee}</strong>.
                </p>
              )}
            </div>
          )}

          {(isError || payError) && (
            <p className="text-xs text-red-500">{payError || 'Check-in failed — please try again'}</p>
          )}

          <div className="flex gap-3 pt-1">
            <button onClick={onClose} className="flex-1 border border-gray-300 text-gray-700 py-2.5 rounded-lg text-sm font-medium hover:bg-gray-50">
              Cancel
            </button>
            <button
              disabled={isPending}
              onClick={() => { setPayError(''); checkinMut.mutate() }}
              className="flex-1 bg-primary text-white py-2.5 rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
            >
              {isPending
                ? (admitCash.isPending ? 'Collecting…' : 'Checking in…')
                : (fee > 0 && !waiveFee && payMode === 'cash')
                  ? 'Check In & Collect Cash'
                  : 'Confirm & Check In'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Reschedule Modal ──────────────────────────────────────────────────────────
function RescheduleModal({ appt, onClose }: { appt: Appointment; onClose: () => void }) {
  const qc = useQueryClient()
  const [newDate, setNewDate] = useState(format(parseISO(appt.slot_time), 'yyyy-MM-dd'))
  const [newSlot, setNewSlot] = useState('')
  const [notes, setNotes] = useState(appt.notes ?? '')

  const { data: slots = [] } = useQuery<AppointmentSlot[]>({
    queryKey: ['slots', appt.doctor_id, newDate],
    queryFn: () => appointmentService.slots(appt.doctor_id, newDate),
    enabled: !!newDate,
  })

  const mut = useMutation({
    mutationFn: () => appointmentService.reschedule(appt.id, newSlot, notes || undefined),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['appointments'] }); onClose() },
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">Reschedule Appointment</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
        </div>
        <div className="px-6 py-5 space-y-4">
          <div className="bg-gray-50 rounded-lg px-4 py-3 text-xs space-y-1">
            <p className="text-gray-500">Patient: <span className="font-medium text-gray-700">{appt.patient_name}</span>
              {appt.patient_uhid && <span className="ml-1 font-mono text-blue-500">({appt.patient_uhid})</span>}
            </p>
            <p className="text-gray-500">Doctor: <span className="font-medium text-gray-700">Dr. {appt.doctor_name}</span></p>
            <p className="text-gray-500">Current slot: <span className="font-medium text-gray-700">{format(parseISO(appt.slot_time), 'dd MMM yyyy, HH:mm')}</span></p>
          </div>

          <div className="space-y-1">
            <label className="block text-sm font-medium text-gray-700">New Date</label>
            <input
              type="date"
              value={newDate}
              onChange={e => { setNewDate(e.target.value); setNewSlot('') }}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
          </div>

          {newDate && (
            <div className="space-y-2">
              <label className="block text-sm font-medium text-gray-700">New Slot</label>
              {slots.length === 0 ? (
                <p className="text-xs text-gray-400">No slots available for this date</p>
              ) : (
                <div className="grid grid-cols-4 gap-1.5">
                  {slots.map(slot => {
                    const t = format(parseISO(slot.slot_time), 'HH:mm')
                    return (
                      <button
                        key={slot.slot_time}
                        type="button"
                        disabled={!slot.is_available}
                        onClick={() => setNewSlot(slot.slot_time)}
                        className={`px-2 py-1.5 rounded text-xs font-medium border transition-colors ${
                          !slot.is_available
                            ? 'bg-gray-100 text-gray-300 cursor-not-allowed border-gray-100'
                            : newSlot === slot.slot_time
                              ? 'bg-primary text-white border-primary'
                              : 'bg-white text-gray-700 border-gray-200 hover:border-primary'
                        }`}
                      >{t}</button>
                    )
                  })}
                </div>
              )}
            </div>
          )}

          <div className="space-y-1">
            <label className="block text-sm font-medium text-gray-700">Notes (optional)</label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={2}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none"
            />
          </div>

          {mut.isError && (
            <p className="text-xs text-red-500">Reschedule failed — slot may already be taken</p>
          )}

          <div className="flex justify-end gap-3 pt-1">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">
              Cancel
            </button>
            <button
              disabled={!newSlot || mut.isPending}
              onClick={() => mut.mutate()}
              className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium disabled:opacity-50"
            >
              {mut.isPending ? 'Saving…' : 'Reschedule'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function BookModal({
  onClose,
  selectedDate,
  doctors,
  departments,
}: {
  onClose: () => void
  selectedDate: string
  doctors: Doctor[]
  departments: Department[]
}) {
  const qc = useQueryClient()
  const [patientSearch, setPatientSearch] = useState('')
  const [patientResults, setPatientResults] = useState<Patient[]>([])
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null)
  const [filterDeptId, setFilterDeptId] = useState('')
  const [noResults, setNoResults] = useState(false)
  const [showRegisterModal, setShowRegisterModal] = useState(false)

  const { register, handleSubmit, watch, setValue, formState: { errors } } = useForm<BookForm>({
    resolver: zodResolver(bookSchema),
    defaultValues: { type: 'phone', slot_time: '' },
  })

  const watchedDoctorId = watch('doctor_id')

  const filteredDoctors = filterDeptId
    ? doctors.filter(d => d.department_id === filterDeptId)
    : doctors

  // Calendar & time-picker state
  const [calSelectedDate, setCalSelectedDate] = useState<Date>(() => parseISO(selectedDate))
  const [pickHour, setPickHour] = useState('9')
  const [pickMin, setPickMin] = useState('00')
  const [pickAmPm, setPickAmPm] = useState<'AM' | 'PM'>('AM')

  // Derived: today helpers (re-computed each render — cheap)
  const todayStr = format(new Date(), 'yyyy-MM-dd')
  const selStr   = format(calSelectedDate, 'yyyy-MM-dd')
  const isSelectedToday = selStr === todayStr

  // Auto-correct time forward whenever the selected date changes to today
  useEffect(() => {
    const now = new Date()
    if (format(calSelectedDate, 'yyyy-MM-dd') !== format(now, 'yyyy-MM-dd')) return
    const nowH = now.getHours()
    const nowM = now.getMinutes()
    // If currently in AM but it's already afternoon, switch to PM
    let ampm: 'AM' | 'PM' = pickAmPm
    if (ampm === 'AM' && nowH >= 12) ampm = 'PM'
    const h24 = to24h(parseInt(pickHour, 10), ampm)
    const m   = parseInt(pickMin, 10)
    if (h24 < nowH || (h24 === nowH && m <= nowM)) {
      // advance to the next 5-min slot from now
      const nextM5 = Math.ceil((nowM + 1) / 5) * 5
      if (nextM5 < 60) {
        const h12 = nowH % 12 || 12
        setPickAmPm(nowH >= 12 ? 'PM' : 'AM')
        setPickHour(String(h12))
        setPickMin(String(nextM5).padStart(2, '0'))
      } else {
        const nextH24 = nowH + 1
        setPickAmPm(nextH24 >= 12 ? 'PM' : 'AM')
        setPickHour(String(nextH24 % 12 || 12))
        setPickMin('00')
      }
    } else if (ampm !== pickAmPm) {
      setPickAmPm(ampm)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calSelectedDate])

  // Time disabling helpers
  const nowSnap = new Date()
  const nowH24  = nowSnap.getHours()
  const nowMin  = nowSnap.getMinutes()

  const isAmPmDisabled = (p: 'AM' | 'PM') =>
    isSelectedToday && p === 'AM' && nowH24 >= 12

  const isHourDisabled = (h: number) => {
    if (!isSelectedToday) return false
    const h24 = to24h(h, pickAmPm)
    return h24 < nowH24 || (h24 === nowH24 && nowMin >= 55)
  }

  const isMinDisabled = (m: number) => {
    if (!isSelectedToday) return false
    const h24 = to24h(parseInt(pickHour, 10), pickAmPm)
    return h24 < nowH24 || (h24 === nowH24 && m <= nowMin)
  }

  // Consultation fee for selected doctor
  const selectedDoctor = doctors.find(d => d.id === watchedDoctorId)

  // Sync slot_time whenever date or time changes
  useEffect(() => {
    const h24 = to24h(parseInt(pickHour, 10), pickAmPm)
    const dt = new Date(
      calSelectedDate.getFullYear(),
      calSelectedDate.getMonth(),
      calSelectedDate.getDate(),
      h24,
      parseInt(pickMin, 10),
      0,
    )
    setValue('slot_time', dt.toISOString())
  }, [calSelectedDate, pickHour, pickMin, pickAmPm, setValue])

  const bookMut = useMutation({
    mutationFn: appointmentService.book,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['appointments'] })
      onClose()
    },
  })

  const searchPatients = async (q: string) => {
    if (q.length < 2) { setPatientResults([]); setNoResults(false); return }
    const results = await patientService.list(q)
    setPatientResults(results)
    setNoResults(results.length === 0)
  }

  const selectPatient = (p: Patient) => {
    setSelectedPatient(p)
    setValue('patient_id', p.id)
    setPatientSearch(`${p.first_name} ${p.last_name} (${p.uhid})`)
    setPatientResults([])
    setNoResults(false)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">Book Appointment</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
        </div>
        <form
          onSubmit={handleSubmit(data => bookMut.mutate({ ...data, slot_time: data.slot_time }))}
          className="px-6 py-5 space-y-4"
        >
          {/* Patient search */}
          <div className="space-y-1 relative">
            <label className="block text-sm font-medium text-gray-700">Patient</label>
            <input
              value={patientSearch}
              onChange={e => { setPatientSearch(e.target.value); searchPatients(e.target.value) }}
              className={inputCls}
              placeholder="Search by name, phone or UHID…"
            />
            {errors.patient_id && <p className="text-xs text-red-500">Select a patient</p>}
            {patientResults.length > 0 && (
              <ul className="absolute z-20 left-0 right-0 bg-white border border-gray-200 rounded-lg shadow-lg mt-1 max-h-48 overflow-y-auto">
                {patientResults.map(p => (
                  <li
                    key={p.id}
                    onClick={() => selectPatient(p)}
                    className="px-4 py-2 hover:bg-gray-50 cursor-pointer text-sm"
                  >
                    <span className="font-medium">{p.first_name} {p.last_name}</span>
                    <span className="text-gray-400 ml-2">{p.uhid} · {p.phone}</span>
                  </li>
                ))}
              </ul>
            )}
            {noResults && !selectedPatient && (
              <p className="text-xs text-gray-500 mt-1">
                No patients found.{' '}
                <button
                  type="button"
                  onClick={() => setShowRegisterModal(true)}
                  className="text-primary font-medium underline hover:text-primary/80"
                >
                  Click here to register a new patient
                </button>
              </p>
            )}
            {selectedPatient && (
              <p className="text-xs text-green-600">✓ {selectedPatient.uhid} selected</p>
            )}
          </div>

          {/* Department filter */}
          {departments.length > 0 && (
            <div className="space-y-1">
              <label className="block text-sm font-medium text-gray-700">Filter by Department</label>
              <select
                value={filterDeptId}
                onChange={e => { setFilterDeptId(e.target.value); setValue('doctor_id', ''); setValue('slot_time', '') }}
                className={inputCls}
              >
                <option value="">All Departments</option>
                {departments.map(d => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </div>
          )}

          {/* Doctor */}
          <div className="space-y-1">
            <label className="block text-sm font-medium text-gray-700">Doctor</label>
            <select
              {...register('doctor_id')}
              onChange={e => { register('doctor_id').onChange(e); setValue('slot_time', '') }}
              className={inputCls}
            >
              <option value="">— Select doctor —</option>
              {filteredDoctors.map(d => (
                <option key={d.id} value={d.id}>{d.full_name} · {d.specialization}</option>
              ))}
            </select>
            {errors.doctor_id && <p className="text-xs text-red-500">{errors.doctor_id.message}</p>}
            {selectedDoctor && selectedDoctor.consultation_fee > 0 && (
              <p className="text-xs text-blue-600 bg-blue-50 rounded-lg px-3 py-1.5 mt-1">
                Consultation fee: <strong>₹{selectedDoctor.consultation_fee}</strong>
              </p>
            )}
          </div>

          {/* Type */}
          <div className="space-y-1">
            <label className="block text-sm font-medium text-gray-700">Type</label>
            <select {...register('type')} className={inputCls}>
              <option value="phone">Phone Call</option>
              <option value="online">Online (Website)</option>
              <option value="walkin">Walk-in</option>
            </select>
          </div>

          {/* Date & Time Picker */}
          <div className="space-y-2">
            <label className="block text-sm font-medium text-gray-700">Appointment Date &amp; Time</label>

            {/* ── Date row ── */}
            <div className="flex items-center gap-2">
              {/* Left arrow — only shown when selected date is NOT today */}
              {!isSelectedToday && (
                <button
                  type="button"
                  onClick={() => setCalSelectedDate(d => subDays(d, 1))}
                  className="p-2 rounded-lg border border-gray-200 hover:bg-gray-100 text-gray-500 flex-shrink-0"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                </button>
              )}

              {/* Calendar icon + native date input */}
              <div className="flex-1 flex items-center border border-gray-300 rounded-lg bg-white overflow-hidden">
                <svg className="w-4 h-4 text-gray-400 ml-3 flex-shrink-0 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
                <input
                  type="date"
                  value={selStr}
                  min={todayStr}
                  onChange={e => {
                    if (e.target.value) setCalSelectedDate(new Date(e.target.value + 'T00:00:00'))
                  }}
                  className="flex-1 px-3 py-2 text-sm text-gray-700 bg-transparent focus:outline-none cursor-pointer"
                />
              </div>

              {/* Right arrow — always shown */}
              <button
                type="button"
                onClick={() => setCalSelectedDate(d => addDays(d, 1))}
                className="p-2 rounded-lg border border-gray-200 hover:bg-gray-100 text-gray-500 flex-shrink-0"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </button>
            </div>

            {/* ── Time row ── */}
            <div className="flex items-end gap-2">
              {/* Hour */}
              <div className="flex-1 space-y-1">
                <label className="block text-[10px] font-medium text-gray-500 uppercase tracking-wide">Hour</label>
                <select
                  value={pickHour}
                  onChange={e => setPickHour(e.target.value)}
                  className={inputCls}
                >
                  {Array.from({ length: 12 }, (_, i) => i + 1).map(h => (
                    <option key={h} value={String(h)} disabled={isHourDisabled(h)}>
                      {String(h).padStart(2, '0')}
                    </option>
                  ))}
                </select>
              </div>

              <span className="pb-2.5 text-gray-400 font-bold text-sm">:</span>

              {/* Minute */}
              <div className="flex-1 space-y-1">
                <label className="block text-[10px] font-medium text-gray-500 uppercase tracking-wide">Min</label>
                <select
                  value={pickMin}
                  onChange={e => setPickMin(e.target.value)}
                  className={inputCls}
                >
                  {Array.from({ length: 12 }, (_, i) => i * 5).map(m => {
                    const mStr = String(m).padStart(2, '0')
                    return (
                      <option key={m} value={mStr} disabled={isMinDisabled(m)}>{mStr}</option>
                    )
                  })}
                </select>
              </div>

              {/* AM / PM toggle */}
              <div className="space-y-1">
                <label className="block text-[10px] font-medium text-gray-500 uppercase tracking-wide">Period</label>
                <div className="flex rounded-lg border border-gray-200 overflow-hidden">
                  {(['AM', 'PM'] as const).map(p => {
                    const dis = isAmPmDisabled(p)
                    return (
                      <button
                        key={p}
                        type="button"
                        disabled={dis}
                        onClick={() => !dis && setPickAmPm(p)}
                        className={`px-3 py-2 text-xs font-medium transition-colors ${
                          dis
                            ? 'bg-gray-50 text-gray-300 cursor-not-allowed'
                            : pickAmPm === p
                              ? 'bg-primary text-white'
                              : 'bg-white text-gray-600 hover:bg-gray-50'
                        }`}
                      >{p}</button>
                    )
                  })}
                </div>
              </div>

              {/* Live preview */}
              <div className="pb-2 text-sm font-semibold text-primary tabular-nums whitespace-nowrap">
                {String(pickHour).padStart(2, '0')}:{pickMin} {pickAmPm}
              </div>
            </div>

            {/* Summary */}
            <p className="text-xs text-green-700 font-medium">
              &#10003; {format(calSelectedDate, 'EEE, dd MMM yyyy')} &nbsp;&middot;&nbsp; {String(pickHour).padStart(2, '0')}:{pickMin} {pickAmPm}
            </p>
            {errors.slot_time && <p className="text-xs text-red-500">Select a date and time</p>}
          </div>

          {/* Notes */}
          <div className="space-y-1">
            <label className="block text-sm font-medium text-gray-700">Notes (optional)</label>
            <textarea {...register('notes')} rows={2} className={inputCls} placeholder="Reason for visit…" />
          </div>

          {bookMut.isError && (
            <p className="text-xs text-red-500">
              {(bookMut.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Booking failed'}
            </p>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
              Cancel
            </button>
            <button
              type="submit"
              disabled={bookMut.isPending}
              className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
            >
              {bookMut.isPending ? 'Booking…' : 'Book Appointment'}
            </button>
          </div>
        </form>
      </div>
      {showRegisterModal && (
        <RegisterPatientModal
          onClose={() => setShowRegisterModal(false)}
          prefillPhone={/^\d/.test(patientSearch) ? patientSearch.replace(/\D/g, '').slice(0, 15) : undefined}
          onSuccess={patient => {
            selectPatient(patient)
            setShowRegisterModal(false)
          }}
        />
      )}
    </div>
  )
}

// ── Slot Grid (sidebar) ───────────────────────────────────────────────────────

function SlotGrid({
  doctorId,
  selectedDate,
}: {
  doctorId: string
  selectedDate: string
}) {
  const { data: slots = [], isLoading } = useQuery<AppointmentSlot[]>({
    queryKey: ['slots', doctorId, selectedDate],
    queryFn: () => appointmentService.slots(doctorId, selectedDate),
    enabled: !!doctorId,
  })

  if (isLoading) return <p className="text-sm text-gray-400 py-4 text-center">Loading slots…</p>
  if (!doctorId) return <p className="text-sm text-gray-400 py-4 text-center">Select a doctor to see slots</p>

  return (
    <div>
      <h3 className="text-sm font-medium text-gray-700 mb-3">Slot availability</h3>
      <div className="grid grid-cols-3 gap-1.5">
        {slots.map(slot => {
          const t = format(parseISO(slot.slot_time), 'HH:mm')
          const isBooked = !slot.is_available
          return (
            <div
              key={slot.slot_time}
              className={`px-2 py-2 rounded text-xs text-center border ${
                isBooked
                  ? 'bg-red-50 text-red-500 border-red-100'
                  : 'bg-green-50 text-green-700 border-green-100'
              }`}
            >
              {t}
              <div className="text-[10px] mt-0.5">{isBooked ? 'booked' : 'free'}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function AppointmentsPage() {
  const qc = useQueryClient()
  const [selectedDate, setSelectedDate] = useState<string>(format(new Date(), 'yyyy-MM-dd'))
  const [filterDoctorId, setFilterDoctorId] = useState<string>('')
  const [showBook, setShowBook] = useState(false)
  const [rescheduleAppt, setRescheduleAppt] = useState<Appointment | null>(null)
  const [checkInAppt, setCheckInAppt] = useState<Appointment | null>(null)

  const { data: doctors = [] } = useQuery({
    queryKey: ['doctors'],
    queryFn: () => doctorService.list(),
  })

  const { data: departments = [] } = useQuery({
    queryKey: ['departments'],
    queryFn: () => departmentService.list(),
  })

  const { data: appointments = [], isLoading } = useQuery<Appointment[]>({
    queryKey: ['appointments', selectedDate, filterDoctorId],
    queryFn: () => appointmentService.list({
      date: selectedDate,
      doctor_id: filterDoctorId || undefined,
    }),
  })

  // Real-time: refresh when any appointment or queue event fires
  const invalidateAppts = useCallback(() =>
    qc.invalidateQueries({ queryKey: ['appointments'] }), [qc])
  useWebSocket('appointment:update', invalidateAppts)
  useWebSocket('queue:update', invalidateAppts)

  const cancelMut = useMutation({
    mutationFn: appointmentService.cancel,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['appointments'] }),
  })

  const prevDay = () => setSelectedDate(format(subDays(new Date(selectedDate), 1), 'yyyy-MM-dd'))
  const nextDay = () => setSelectedDate(format(addDays(new Date(selectedDate), 1), 'yyyy-MM-dd'))

  const counts = {
    total: appointments.length,
    checkedIn: appointments.filter(a => a.status === 'checked_in').length,
    completed: appointments.filter(a => a.status === 'completed').length,
    cancelled: appointments.filter(a => a.status === 'cancelled').length,
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Appointments</h1>
          <p className="text-sm text-gray-500 mt-0.5">Schedule, manage and check-in patients</p>
        </div>
        <button
          onClick={() => setShowBook(true)}
          className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90"
        >
          + Book Appointment
        </button>
      </div>

      {/* Date navigator */}
      <div className="flex items-center gap-4 mb-5">
        <button onClick={prevDay} className="p-1.5 rounded hover:bg-gray-100 text-gray-500">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div className="flex items-center gap-3">
          <input
            type="date"
            value={selectedDate}
            onChange={e => setSelectedDate(e.target.value)}
            className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
          <span className="text-sm text-gray-600 font-medium">
            {format(new Date(selectedDate), 'EEEE, dd MMMM yyyy')}
          </span>
        </div>
        <button onClick={nextDay} className="p-1.5 rounded hover:bg-gray-100 text-gray-500">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </button>
        <button
          onClick={() => setSelectedDate(format(new Date(), 'yyyy-MM-dd'))}
          className="px-3 py-1.5 text-xs font-medium text-primary border border-primary/30 rounded-lg hover:bg-primary/5"
        >
          Today
        </button>
      </div>

      {/* Stats chips */}
      <div className="flex gap-3 mb-5">
        {[
          { label: 'Total', value: counts.total, color: 'bg-gray-100 text-gray-700' },
          { label: 'Checked In', value: counts.checkedIn, color: 'bg-yellow-100 text-yellow-700' },
          { label: 'Completed', value: counts.completed, color: 'bg-green-100 text-green-700' },
          { label: 'Cancelled', value: counts.cancelled, color: 'bg-red-100 text-red-600' },
        ].map(s => (
          <span key={s.label} className={`px-3 py-1.5 rounded-full text-xs font-medium ${s.color}`}>
            {s.label}: {s.value}
          </span>
        ))}
      </div>

      <div className="flex gap-6">
        {/* Appointment list */}
        <div className="flex-1">
          {/* Doctor filter */}
          <div className="mb-3">
            <select
              value={filterDoctorId}
              onChange={e => setFilterDoctorId(e.target.value)}
              className="px-3 py-2 border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-primary/30 w-64"
            >
              <option value="">All Doctors</option>
              {doctors.map(d => (
                <option key={d.id} value={d.id}>{d.full_name}</option>
              ))}
            </select>
          </div>

          {isLoading ? (
            <p className="text-sm text-gray-400 text-center py-12">Loading…</p>
          ) : appointments.length === 0 ? (
            <div className="border border-dashed border-gray-200 rounded-xl py-16 text-center">
              <p className="text-gray-400 text-sm">No appointments for this day</p>
              <button
                onClick={() => setShowBook(true)}
                className="mt-3 text-sm text-primary hover:underline"
              >
                Book the first one →
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              {appointments.map(appt => (
                <div
                  key={appt.id}
                  className="bg-white border border-gray-200 rounded-xl px-5 py-4 flex items-center gap-4 hover:border-gray-300 transition-colors"
                >
                  {/* Time */}
                  <div className="w-14 text-center flex-shrink-0">
                    <p className="text-base font-bold text-gray-900 tabular-nums">
                      {format(parseISO(appt.slot_time), 'HH:mm')}
                    </p>
                    <p className="text-[10px] text-gray-400 capitalize">{appt.type.replace('_', ' ')}</p>
                  </div>

                  <div className="w-px h-10 bg-gray-200 flex-shrink-0" />

                  {/* Patient / Doctor */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {appt.patient_name ?? '—'}
                    </p>
                    {appt.patient_uhid && (
                      <p className="text-[10px] font-mono text-blue-500">{appt.patient_uhid}</p>
                    )}
                    <p className="text-xs text-gray-500 truncate mt-0.5">
                      Dr. {appt.doctor_name ?? '—'}
                      {appt.notes && <span className="text-gray-400 ml-2">· {appt.notes}</span>}
                    </p>
                  </div>

                  {/* Status */}
                  <StatusBadge status={appt.status} />

                  {/* Actions */}
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {(appt.status === 'scheduled' || appt.status === 'confirmed') && (
                      <>
                        <button
                          onClick={() => setCheckInAppt(appt)}
                          className="px-3 py-1.5 bg-green-600 text-white rounded-lg text-xs font-medium hover:bg-green-700"
                        >
                          Check In
                        </button>
                        <button
                          onClick={() => setRescheduleAppt(appt)}
                          className="px-3 py-1.5 bg-blue-50 text-blue-600 rounded-lg text-xs font-medium hover:bg-blue-100"
                        >
                          Reschedule
                        </button>
                        <button
                          onClick={() => cancelMut.mutate(appt.id)}
                          disabled={cancelMut.isPending}
                          className="px-3 py-1.5 bg-red-50 text-red-600 rounded-lg text-xs font-medium hover:bg-red-100 disabled:opacity-50"
                        >
                          Cancel
                        </button>
                      </>
                    )}
                    {appt.status === 'checked_in' && (
                      <span className="text-xs text-yellow-600 font-medium">In queue</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Slot grid sidebar */}
        <div className="w-64 flex-shrink-0">
          <div className="bg-white border border-gray-200 rounded-xl p-4 sticky top-6">
            <SlotGrid
              doctorId={filterDoctorId}
              selectedDate={selectedDate}
            />
          </div>
        </div>
      </div>

      {showBook && (
        <BookModal
          onClose={() => setShowBook(false)}
          selectedDate={selectedDate}
          doctors={doctors}
          departments={departments}
        />
      )}

      {rescheduleAppt && (
        <RescheduleModal
          appt={rescheduleAppt}
          onClose={() => setRescheduleAppt(null)}
        />
      )}

      {checkInAppt && (
        <CheckInConfirmModal
          appt={checkInAppt}
          doctor={doctors.find(d => d.id === checkInAppt.doctor_id)}
          onClose={() => setCheckInAppt(null)}
        />
      )}
    </div>
  )
}
