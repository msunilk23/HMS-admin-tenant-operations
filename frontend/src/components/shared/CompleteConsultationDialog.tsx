import { useEffect, useRef } from 'react'

export interface CompleteConsultationDialogProps {
  open: boolean
  isSubmitting: boolean
  errorMessage?: string
  onCancel: () => void
  onConfirm: () => void
}

/**
 * Shared confirmation dialog for the PF-1 "Complete Consultation" action.
 * Used by both ConsultationPage (Path B — no prescription) and
 * PrescriptionPage (Path A — with prescription/Lab orders).
 */
export default function CompleteConsultationDialog({
  open,
  isSubmitting,
  errorMessage,
  onCancel,
  onConfirm,
}: CompleteConsultationDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (open) cancelRef.current?.focus()
  }, [open])

  useEffect(() => {
    if (!open) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isSubmitting) onCancel()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, isSubmitting, onCancel])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="complete-consultation-title"
        aria-describedby="complete-consultation-description"
        className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 space-y-4"
      >
        <h2 id="complete-consultation-title" className="text-lg font-semibold text-gray-900">
          Complete Consultation?
        </h2>
        <ul id="complete-consultation-description" className="text-sm text-gray-600 space-y-2 list-disc pl-5">
          <li>The OPD consultation will be closed.</li>
          <li>The patient will be routed independently to applicable departments.</li>
          <li>Further clinical changes require the controlled amendment workflow.</li>
        </ul>
        {errorMessage && (
          <p role="alert" className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
            {errorMessage}
          </p>
        )}
        <div className="flex gap-3 justify-end pt-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            disabled={isSubmitting}
            className="border border-gray-300 text-gray-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-50 disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isSubmitting}
            aria-busy={isSubmitting}
            className="bg-emerald-700 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-emerald-800 disabled:opacity-60"
          >
            {isSubmitting ? 'Completing…' : 'Yes, Complete Consultation'}
          </button>
        </div>
      </div>
    </div>
  )
}
