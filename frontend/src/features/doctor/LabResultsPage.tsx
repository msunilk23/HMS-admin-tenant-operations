/**
 * Doctor Lab Results Page
 *
 * Displays verified lab results for visits assigned to the authenticated
 * Doctor only. Uses the authenticated apiClient (JWT + silent refresh) via
 * labService/visitService — never raw fetch(). visit_id is a real backend
 * filter; the server further restricts results to the doctor's own visits.
 */

import { useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useWebSocket } from '@/hooks/useWebSocket'
import { labService } from '@/services/labService'
import { visitService } from '@/services/visitService'
import type { LabOrder, Visit } from '@/types/common'

interface LabTestDisplay {
  test?: string
  test_id?: string
  test_code?: string
  test_name?: string
  unit?: string
  reference_range?: string
}

interface LabResultDisplay {
  testCode: string
  testName: string
  resultValue: string | null
  unit: string
  referenceRange: string
  criticalFlag: boolean
  status: string
  verifiedAt?: string
  verifiedBy?: string
}

function formatDate(dateStr: string | undefined): string {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

function CriticalBadge({ isCritical }: { isCritical?: boolean }) {
  if (!isCritical) return <span className="text-gray-400">—</span>
  return <span className="inline-block px-2 py-1 text-xs font-semibold text-red-700 bg-red-100 rounded">CRITICAL</span>
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    verified: 'bg-green-100 text-green-700',
    result_ready: 'bg-yellow-100 text-yellow-700',
    processing: 'bg-purple-100 text-purple-700',
  }
  return (
    <span className={`inline-block px-2 py-1 text-xs font-semibold rounded ${styles[status] || 'bg-gray-100 text-gray-600'}`}>
      {status?.toUpperCase() || 'UNKNOWN'}
    </span>
  )
}

export default function DoctorLabResultsPage() {
  const qc = useQueryClient()
  const [selectedVisitId, setSelectedVisitId] = useState<string | null>(null)
  const [dateRange, setDateRange] = useState<{ from?: string; to?: string }>({})

  // The backend already scopes visits to this doctor's own patients for
  // role=doctor — no client-side filtering needed or trusted.
  const { data: visits = [] } = useQuery({
    queryKey: ['my-visits', 'lab-results'],
    queryFn: () => visitService.list({ status: 'CONSULTATION_COMPLETED' }),
    staleTime: 5 * 60 * 1000,
  })

  const { data: labOrders = [], isLoading, isError } = useQuery({
    queryKey: ['lab-results', selectedVisitId],
    queryFn: () => labService.listOrders({ visit_id: selectedVisitId!, status: 'verified' }),
    enabled: !!selectedVisitId,
    staleTime: 3 * 60 * 1000,
  })

  // WebSocket: real-time result updates
  useWebSocket('lab:update', useCallback(() => {
    if (selectedVisitId) {
      qc.invalidateQueries({ queryKey: ['lab-results', selectedVisitId] })
    }
  }, [selectedVisitId, qc]))

  // Transform lab orders + results into display table
  const tableRows: LabResultDisplay[] = labOrders.flatMap((order: LabOrder) => {
    const results = order.result?.results || {}
    const criticalFlags = order.result?.critical_flags || {}
    const testsArray = order.tests || []

    return testsArray.map((test: LabTestDisplay, idx: number) => {
      const resultKey = test.test_code || test.test
      return {
        testCode: resultKey || `Test ${idx + 1}`,
        testName: test.test_name || test.test || 'Unknown Test',
        resultValue: resultKey ? results[resultKey] || null : null,
        unit: test.unit || '—',
        referenceRange: test.reference_range || '—',
        criticalFlag: resultKey ? Boolean(criticalFlags[resultKey]) : false,
        status: order.status,
        verifiedAt: order.result?.verified_at,
        verifiedBy: order.result?.verified_by_user_id,
      }
    })
  })

  // Apply date range filter if provided
  const filteredRows = dateRange.from || dateRange.to
    ? tableRows.filter(row => {
        if (!row.verifiedAt) return false
        const rowDate = new Date(row.verifiedAt).toISOString().split('T')[0]
        const fromMatch = !dateRange.from || rowDate >= dateRange.from
        const toMatch = !dateRange.to || rowDate <= dateRange.to
        return fromMatch && toMatch
      })
    : tableRows

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-gray-900">Lab Results</h1>
          <p className="mt-2 text-sm text-gray-600">View verified lab test results for your patients</p>
        </div>

        {/* Filters */}
        <div className="bg-white rounded-lg shadow p-6 mb-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Visit Filter */}
            <div>
              <label htmlFor="lab-visit" className="block text-sm font-medium text-gray-700 mb-2">Select Patient/Visit</label>
              <select
                id="lab-visit"
                value={selectedVisitId || ''}
                onChange={(e) => setSelectedVisitId(e.target.value || null)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500"
              >
                <option value="">— Select a visit —</option>
                {visits.map((visit: Visit) => (
                  <option key={visit.id} value={visit.id}>
                    {visit.patient?.first_name || 'Unknown'} ({visit.patient?.uhid || 'Unknown'}) • {formatDate(visit.created_at)}
                  </option>
                ))}
              </select>
            </div>

            {/* Date From */}
            <div>
              <label htmlFor="lab-date-from" className="block text-sm font-medium text-gray-700 mb-2">From Date</label>
              <input
                id="lab-date-from"
                type="date"
                value={dateRange.from || ''}
                onChange={(e) => setDateRange({ ...dateRange, from: e.target.value || undefined })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500"
              />
            </div>

            {/* Date To */}
            <div>
              <label htmlFor="lab-date-to" className="block text-sm font-medium text-gray-700 mb-2">To Date</label>
              <input
                id="lab-date-to"
                type="date"
                value={dateRange.to || ''}
                onChange={(e) => setDateRange({ ...dateRange, to: e.target.value || undefined })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500"
              />
            </div>
          </div>
        </div>

        {/* Results Table */}
        {selectedVisitId ? (
          <div className="bg-white rounded-lg shadow overflow-hidden">
            {isLoading ? (
              <div className="text-center py-12" role="status">
                <p className="text-gray-500 text-sm">Loading lab results…</p>
              </div>
            ) : isError ? (
              <div className="text-center py-12" role="alert">
                <p className="text-red-600 text-sm">Could not load lab results. Please try again.</p>
              </div>
            ) : filteredRows.length > 0 ? (
              <table className="w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Test Code</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Test Name</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Result</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Unit</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Reference Range</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Critical</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Verified</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {filteredRows.map((row, idx) => (
                    <tr key={idx} className={row.criticalFlag ? 'bg-red-50' : ''}>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-mono text-gray-900">{row.testCode}</td>
                      <td className="px-6 py-4 text-sm text-gray-900">{row.testName}</td>
                      <td className={`px-6 py-4 whitespace-nowrap text-sm font-semibold ${row.criticalFlag ? 'text-red-700' : 'text-gray-900'}`}>
                        {row.resultValue || '—'}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">{row.unit}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">{row.referenceRange}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm">
                        <CriticalBadge isCritical={row.criticalFlag} />
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm">
                        <StatusBadge status={row.status} />
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">{formatDate(row.verifiedAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="text-center py-12">
                <p className="text-gray-500 text-sm">No lab results found for this visit.</p>
              </div>
            )}
          </div>
        ) : (
          <div className="bg-white rounded-lg shadow p-12 text-center">
            <p className="text-gray-500 text-base">Select a patient/visit to view lab results</p>
          </div>
        )}
      </div>
    </div>
  )
}
