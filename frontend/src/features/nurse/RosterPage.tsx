import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { nurseRosterService } from '@/services/nurseRosterService'

const today = new Date().toISOString().slice(0, 10)

export default function RosterPage() {
  const qc = useQueryClient()
  const [rosterDate, setRosterDate] = useState(today)
  const { data: rows = [], isLoading } = useQuery({
    queryKey: ['nurse-roster', rosterDate],
    queryFn: () => nurseRosterService.list({ roster_date: rosterDate }),
  })
  const { mutate: update } = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { is_present: boolean; is_active?: boolean } }) =>
      nurseRosterService.update(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['nurse-roster'] }),
  })

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Nurse Roster</h1>
          <p className="text-sm text-gray-500 mt-1">Assignments, attendance, and substitutions</p>
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
          <div className="p-8 text-sm text-gray-500">Loading roster…</div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-sm text-gray-500">No roster entries for this date.</div>
        ) : (
          <div className="divide-y divide-gray-100">
            {rows.map(row => (
              <div key={row.id} className="px-5 py-4 flex items-center justify-between gap-4">
                <div>
                  <p className="font-medium text-gray-900">{row.nurse_name || 'Nurse'}</p>
                  <p className="text-sm text-gray-500">
                    {row.department_name || 'Department'} · {row.shift} · {row.room || 'Room not assigned'}
                  </p>
                  {row.substitute_user_id && (
                    <p className="text-xs text-amber-700 mt-1">Substitution recorded</p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => update({ id: row.id, data: { is_present: !row.is_present } })}
                  className={`px-3 py-2 rounded-lg text-sm font-medium ${row.is_present ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}
                >
                  {row.is_present ? 'Present' : 'Mark present'}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
