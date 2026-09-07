import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ConsultationPage from './ConsultationPage'
import { visitService, vitalsService, consultationService, type ConsultationCreate } from '@/services/visitService'
import { patientService } from '@/services/patientService'
import { clinicalAlertService } from '@/services/clinicalAlertService'
import { masterDataService } from '@/services/masterDataService'
import type { Visit } from '@/types/common'

const navigateMock = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => navigateMock }
})
vi.mock('@/hooks/useWebSocket', () => ({ useWebSocket: vi.fn() }))
vi.mock('@/services/visitService', () => ({
  visitService: { list: vi.fn(), updateStatus: vi.fn() },
  vitalsService: { get: vi.fn() },
  consultationService: { create: vi.fn(), update: vi.fn(), get: vi.fn() },
}))
vi.mock('@/services/patientService', () => ({
  patientService: { getHistory: vi.fn() },
}))
vi.mock('@/services/clinicalAlertService', () => ({
  clinicalAlertService: { listForPatient: vi.fn() },
}))
vi.mock('@/services/masterDataService', () => ({
  masterDataService: { searchIcd10: vi.fn() },
}))

const mockedVisitService = vi.mocked(visitService)
const mockedVitalsService = vi.mocked(vitalsService)
const mockedConsultationService = vi.mocked(consultationService)
const mockedPatientService = vi.mocked(patientService)

const visit = {
  id: 'visit-1',
  patient_id: 'patient-1',
  doctor_id: 'doctor-1',
  status: 'WAITING_FOR_DOCTOR',
  created_at: '2026-09-07T08:00:00Z',
  patient_name: 'Asha Patient',
  token_no: 12,
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <ConsultationPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function callInAndFillChiefComplaint(complaint = 'Fever and cough') {
  await screen.findByText('Asha Patient')
  fireEvent.click(screen.getByRole('button', { name: /call in/i }))
  await screen.findByPlaceholderText(/what brings the patient in today/i)
  fireEvent.change(screen.getByPlaceholderText(/what brings the patient in today/i), { target: { value: complaint } })
}

beforeEach(() => {
  vi.clearAllMocks()
  navigateMock.mockClear()
  mockedVisitService.list.mockImplementation(({ status }: { status?: string } = {}) =>
    Promise.resolve(status === 'vitals_done' ? [visit as unknown as Visit] : []),
  )
  mockedVisitService.updateStatus.mockResolvedValue({ ...visit, status: 'IN_CONSULTATION' } as never)
  mockedVitalsService.get.mockResolvedValue(null as never)
  mockedConsultationService.get.mockResolvedValue(null as never)
  mockedPatientService.getHistory.mockResolvedValue([])
  vi.mocked(clinicalAlertService.listForPatient).mockResolvedValue([])
  vi.mocked(masterDataService.searchIcd10).mockResolvedValue([])
})
afterEach(cleanup)

describe('ConsultationPage — PF-1 completion workflow', () => {
  it('Save Draft does not complete the consultation', async () => {
    mockedConsultationService.create.mockResolvedValue({ id: 'c1', visit_id: 'visit-1', status: 'draft' } as never)
    renderPage()
    await callInAndFillChiefComplaint()
    fireEvent.click(screen.getByRole('button', { name: /save & write prescription/i }))
    await waitFor(() => expect(mockedConsultationService.create).toHaveBeenCalled())
    const payload = mockedConsultationService.create.mock.calls[0][0] as unknown as ConsultationCreate
    expect(payload.status).toBeUndefined()
    expect(navigateMock).toHaveBeenCalledWith('/doctor/prescription/visit-1')
  })

  it('Complete Consultation sends status: "completed"', async () => {
    mockedConsultationService.create.mockResolvedValue({ id: 'c1', visit_id: 'visit-1', status: 'completed' } as never)
    renderPage()
    await callInAndFillChiefComplaint()
    fireEvent.click(screen.getByRole('button', { name: 'Complete Consultation' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /yes, complete consultation/i }))
    await waitFor(() => expect(mockedConsultationService.create).toHaveBeenCalled())
    const payload = mockedConsultationService.create.mock.calls[0][0] as unknown as ConsultationCreate
    expect(payload.status).toBe('completed')
  })

  it('completion confirmation can be cancelled without submitting', async () => {
    renderPage()
    await callInAndFillChiefComplaint()
    fireEvent.click(screen.getByRole('button', { name: 'Complete Consultation' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: /cancel/i }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(mockedConsultationService.create).not.toHaveBeenCalled()
  })

  it('prevents double submission of Complete Consultation', async () => {
    let resolveCreate: (value: Awaited<ReturnType<typeof consultationService.create>>) => void = () => {}
    mockedConsultationService.create.mockImplementation(() => new Promise(resolve => { resolveCreate = resolve }))
    renderPage()
    await callInAndFillChiefComplaint()
    fireEvent.click(screen.getByRole('button', { name: 'Complete Consultation' }))
    const confirmButton = await screen.findByRole('button', { name: /yes, complete consultation/i })
    fireEvent.click(confirmButton)
    await waitFor(() => expect(confirmButton).toBeDisabled())
    fireEvent.click(confirmButton)
    expect(mockedConsultationService.create).toHaveBeenCalledTimes(1)
    resolveCreate({ id: 'c1', visit_id: 'visit-1', status: 'completed', created_at: '2026-09-07T08:00:00Z' })
  })

  it('remains on the page and shows backend message on validation failure', async () => {
    mockedConsultationService.create.mockRejectedValue({
      response: { status: 422, data: { detail: 'Consultation must be finalized before completion' } },
    })
    renderPage()
    await callInAndFillChiefComplaint()
    fireEvent.click(screen.getByRole('button', { name: 'Complete Consultation' }))
    fireEvent.click(await screen.findByRole('button', { name: /yes, complete consultation/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Consultation must be finalized before completion')
    expect(navigateMock).not.toHaveBeenCalled()
  })

  it('completes a consultation with no prescription via ConsultationPage', async () => {
    mockedConsultationService.create.mockResolvedValue({ id: 'c1', visit_id: 'visit-1', status: 'completed' } as never)
    renderPage()
    await callInAndFillChiefComplaint('No medicines needed today')
    fireEvent.click(screen.getByRole('button', { name: 'Complete Consultation' }))
    fireEvent.click(await screen.findByRole('button', { name: /yes, complete consultation/i }))
    expect(await screen.findByRole('heading', { name: /consultation completed/i })).toBeInTheDocument()
    expect(screen.getByText(/opd visit closed/i)).toBeInTheDocument()
  })

  it('success copy does not falsely claim electronic delivery', async () => {
    mockedConsultationService.create.mockResolvedValue({ id: 'c1', visit_id: 'visit-1', status: 'completed' } as never)
    renderPage()
    await callInAndFillChiefComplaint()
    fireEvent.click(screen.getByRole('button', { name: 'Complete Consultation' }))
    fireEvent.click(await screen.findByRole('button', { name: /yes, complete consultation/i }))
    const summary = await screen.findByRole('status')
    expect(summary.textContent).not.toMatch(/e-prescription sent|prescription delivered/i)
    expect(summary.textContent).toMatch(/document generation pending/i)
  })

  it('navigates back to the Doctor queue after successful completion', async () => {
    mockedConsultationService.create.mockResolvedValue({ id: 'c1', visit_id: 'visit-1', status: 'completed' } as never)
    renderPage()
    await callInAndFillChiefComplaint()
    fireEvent.click(screen.getByRole('button', { name: 'Complete Consultation' }))
    fireEvent.click(await screen.findByRole('button', { name: /yes, complete consultation/i }))
    await screen.findByRole('heading', { name: /consultation completed/i })
    fireEvent.click(screen.getByRole('button', { name: /back to doctor queue/i }))
    await waitFor(() => expect(screen.queryByRole('heading', { name: /consultation completed/i })).not.toBeInTheDocument())
  })
})
