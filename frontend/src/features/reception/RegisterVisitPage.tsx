/**
 * Register Visit — receptionist entry point.
 *
 * Lets the receptionist choose how the patient is arriving:
 *   1. Walk-In    → search/register patient, pick department + doctor, issue an OPD token
 *   2. Appointment → find today's (or another date's) booked appointment and check the patient in
 *
 * Both paths ultimately create a Visit linked to a QueueToken and land the visit at
 * WAITING_FOR_NURSE — the receptionist never advances the patient straight to consultation.
 */
import { useNavigate } from 'react-router-dom'

function ChoiceCard({
  title,
  description,
  steps,
  icon,
  onClick,
}: {
  title: string
  description: string
  steps: string[]
  icon: React.ReactNode
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="text-left bg-white border border-gray-200 rounded-2xl p-6 hover:border-primary hover:shadow-md transition-all group flex flex-col gap-4"
    >
      <div className="w-12 h-12 rounded-xl bg-primary/10 text-primary flex items-center justify-center group-hover:bg-primary group-hover:text-white transition-colors">
        {icon}
      </div>
      <div>
        <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
        <p className="text-sm text-gray-500 mt-1">{description}</p>
      </div>
      <ol className="text-xs text-gray-500 space-y-1.5 mt-1">
        {steps.map((s, i) => (
          <li key={s} className="flex gap-2">
            <span className="flex-shrink-0 w-4 h-4 rounded-full bg-gray-100 text-gray-500 text-[10px] font-semibold flex items-center justify-center">{i + 1}</span>
            {s}
          </li>
        ))}
      </ol>
      <span className="mt-2 text-sm font-medium text-primary group-hover:underline">Start →</span>
    </button>
  )
}

export default function RegisterVisitPage() {
  const navigate = useNavigate()

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">Register Visit</h1>
        <p className="text-sm text-gray-500 mt-0.5">How is the patient arriving today?</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        <ChoiceCard
          title="Walk-In"
          description="Patient arrived without a prior appointment."
          steps={[
            'Search patient (or register new)',
            'Select department & doctor',
            'Issue OPD token',
          ]}
          icon={
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M13 16l5-5m0 0l-5-5m5 5H6a4 4 0 00-4 4v1" />
            </svg>
          }
          onClick={() => navigate('/queue?action=issue')}
        />
        <ChoiceCard
          title="Appointment"
          description="Patient booked a slot in advance."
          steps={[
            'Select the appointment date',
            'Find the booked appointment',
            'Check-in to create the OPD token',
          ]}
          icon={
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          }
          onClick={() => navigate('/appointments')}
        />
      </div>
    </div>
  )
}
