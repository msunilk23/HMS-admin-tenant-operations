import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { patientService } from '@/services/patientService'
import type { Patient } from '@/types/common'
import { RegisterPatientModal } from '@/components/shared/RegisterPatientModal'

export default function PatientsPage() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [showInactive, setShowInactive] = useState(false)
  const [selected, setSelected] = useState<Patient | null>(null)
  const [showForm, setShowForm] = useState(false)

  const { data: patients = [], isFetching } = useQuery({
    queryKey: ['patients', search, showInactive],
    queryFn: () => patientService.list(search || undefined, { includeInactive: showInactive }),
    staleTime: 10_000,
  })

  const { mutate: setStatus, isPending: statusPending } = useMutation({
    mutationFn: (patient: Patient) =>
      patient.is_active ? patientService.deactivate(patient.id) : patientService.reactivate(patient.id),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ['patients'] })
      setSelected(updated)
    },
  })

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Patient Registration</h1>
          <p className="text-sm text-gray-500 mt-0.5">Register new patients or search by UHID, name, or phone</p>
        </div>
        <button
          onClick={() => { setShowForm(true); setSelected(null) }}
          className="flex items-center gap-2 bg-primary text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          New Patient
        </button>
      </div>

      {/* Search bar */}
      <div className="relative">
        <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search by UHID, name or phone…"
          className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
        />
        {isFetching && (
          <div className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        )}
      </div>

      <label className="flex items-center gap-2 text-xs text-gray-500">
        <input type="checkbox" checked={showInactive} onChange={e => setShowInactive(e.target.checked)} className="accent-primary" />
        Show deactivated patients
      </label>

      {/* Patient list */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              {['UHID', 'Name', 'Phone', 'Gender', 'Blood Group', 'Status', 'Actions'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {patients.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-10 text-center text-gray-400">
                  {search ? 'No patients found' : 'No patients registered yet'}
                </td>
              </tr>
            ) : patients.map(p => (
              <tr key={p.id} className={`hover:bg-gray-50 transition-colors ${!p.is_active ? 'opacity-60' : ''}`}>
                <td className="px-4 py-3 font-mono text-xs text-blue-600">{p.uhid}</td>
                <td className="px-4 py-3 font-medium text-gray-900">{p.first_name} {p.last_name}</td>
                <td className="px-4 py-3 text-gray-600">{p.phone}</td>
                <td className="px-4 py-3 capitalize text-gray-600">{p.gender}</td>
                <td className="px-4 py-3 text-gray-600">{p.blood_group || '—'}</td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${p.is_active ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                    {p.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => setSelected(p)}
                    className="text-primary hover:underline text-xs font-medium"
                  >
                    View
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Patient detail panel */}
      {selected && (
        <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-end" onClick={() => setSelected(null)}>
          <div className="bg-white w-full max-w-md h-full shadow-xl overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="p-6 border-b border-gray-100 flex items-center justify-between">
              <div>
                <h2 className="font-semibold text-gray-900">{selected.first_name} {selected.last_name}</h2>
                <span className="font-mono text-xs text-blue-600">{selected.uhid}</span>
              </div>
              <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-700">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <dl className="p-6 space-y-3">
              {[
                ['Phone', selected.phone],
                ['Email', selected.email || '—'],
                ['Gender', selected.gender],
                ['Date of Birth', selected.dob || '—'],
                ['Age', selected.age ? `${selected.age} yrs` : '—'],
                ['Blood Group', selected.blood_group || '—'],
                ['Address', selected.address || '—'],
                ['Aadhaar', selected.aadhar_number || '—'],
                ['Insurance Provider', selected.insurance_provider || '—'],
                ['Insurance ID', selected.insurance_id || '—'],
                ['Emergency Contact', selected.emergency_contact_name || '—'],
                ['Emergency Phone', selected.emergency_contact_phone || '—'],
                ['Emergency Relation', selected.emergency_contact_relation || '—'],
                ['Status', selected.is_active ? 'Active' : 'Inactive'],
              ].map(([label, value]) => (
                <div key={label as string} className="flex justify-between text-sm">
                  <dt className="text-gray-500">{label}</dt>
                  <dd className="font-medium text-gray-900 text-right max-w-xs">{value}</dd>
                </div>
              ))}
              <div className="pt-3">
                <button
                  disabled={statusPending}
                  onClick={() => setStatus(selected)}
                  className={`w-full py-2 rounded-lg text-sm font-medium disabled:opacity-60 ${
                    selected.is_active
                      ? 'border border-red-300 text-red-600 hover:bg-red-50'
                      : 'border border-green-300 text-green-700 hover:bg-green-50'
                  }`}
                >
                  {statusPending ? 'Updating…' : selected.is_active ? 'Deactivate Patient' : 'Reactivate Patient'}
                </button>
              </div>
            </dl>
          </div>
        </div>
      )}

      {/* Registration form modal */}
      {showForm && (
        <RegisterPatientModal
          onClose={() => setShowForm(false)}
          onSuccess={() => setShowForm(false)}
        />
      )}
    </div>
  )
}
