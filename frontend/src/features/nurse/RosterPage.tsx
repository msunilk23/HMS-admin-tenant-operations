import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { nurseRosterService } from '@/services/nurseRosterService'

const today = new Date().toISOString().slice(0, 10)

const SHIFT_LABELS: Record<string, string> = { morning: 'Morning', afternoon: 'Afternoon', night: 'Night' }

/**
 * Read-only for Nurse users — Hospital Admin owns roster create/edit/attendance.
 * Also surfaces entries where this Nurse is recorded as a substitute.
 */
export default function RosterPage() {
  const [rosterDate, setRosterDate] = useState(today)
  const { data: rows = [], isLoading, isError } = useQuery({
    queryKey: ['nurse-roster', 'my', rosterDate],
    queryFn: () => nurseRosterService.list({ roster_date: rosterDate }),
  })

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">My Roster</h1>
          <p className="text-sm text-gray-500 mt-1">Your assignments and attendance, as recorded by Hospital Admin</p>
        </div>
        <label className="text-sm text-gray-600">
          Date
          <input
            type="date"
            value={rosterDate}
            onChange={event => setRosterDate(event.target.value)}
            className="ml-2 border border-gray-300 rounded-lg px-3 py-2"
          />
        </label>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-sm text-gray-500" role="status">Loading roster…</div>
        ) : isError ? (
          <div className="p-8 text-sm text-red-600" role="alert">Could not load your roster. Please try again.</div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-sm text-gray-500">No roster entries for this date.</div>
        ) : (
          <div className="divide-y divide-gray-100">
            {rows.map(row => (
              <div key={row.id} className="px-5 py-4 flex items-center justify-between gap-4">
                <div>
                  <p className="font-medium text-gray-900">
                    {row.department_name || 'Department'} · {SHIFT_LABELS[row.shift] || row.shift}
                  </p>
                  <p className="text-sm text-gray-500">
                    Room: {row.room || 'Not assigned'}{row.doctor_name ? ` · Dr. ${row.doctor_name}` : ''}
                  </p>
                  {row.substitute_name && (
                    <p className="text-xs text-amber-700 mt-1">
                      Substitute: {row.substitute_name}{row.substitution_reason ? ` — ${row.substitution_reason}` : ''}
                    </p>
                  )}
                </div>
                <span
                  className={`px-3 py-2 rounded-lg text-sm font-medium ${row.is_present ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}
                >
                  {row.is_present ? 'Present' : 'Not marked present'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
