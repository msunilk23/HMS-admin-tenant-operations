/**
 * Change Password — available to all authenticated roles.
 */
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/services/apiClient'
import { useAuthStore } from '@/features/auth/authStore'

const schema = z
  .object({
    current_password: z.string().min(1, 'Current password is required'),
    new_password: z.string().min(8, 'New password must be at least 8 characters'),
    confirm_password: z.string().min(1, 'Please confirm your new password'),
  })
  .refine(data => data.new_password === data.confirm_password, {
    message: 'Passwords do not match',
    path: ['confirm_password'],
  })

type FormValues = z.infer<typeof schema>

const inputCls =
  'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary'

export default function ChangePasswordPage() {
  const navigate = useNavigate()
  const [success, setSuccess] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  const onSubmit = async (data: FormValues) => {
    setServerError(null)
    try {
      const res = await apiClient.post<{ access_token: string; refresh_token: string; must_change_password: boolean }>('/auth/change-password', {
        current_password: data.current_password,
        new_password: data.new_password,
      })
      useAuthStore.getState().setTokens(res.data.access_token, res.data.refresh_token)
      setSuccess(true)
      reset()
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to change password. Please try again.'
      setServerError(detail)
    }
  }

  return (
    <div className="min-h-full flex items-start justify-center pt-16 px-4">
      <div className="w-full max-w-md">
        <div className="bg-white rounded-xl shadow-sm border border-gray-200">
          {/* Header */}
          <div className="px-6 py-5 border-b border-gray-200">
            <h1 className="text-base font-semibold text-gray-900">Change Password</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              Choose a strong password. Your session stays active after changing.
            </p>
          </div>

          <div className="px-6 py-5">
            {success ? (
              <div className="space-y-4">
                <div className="flex items-center gap-3 p-4 bg-green-50 border border-green-200 rounded-lg">
                  <svg
                    className="w-5 h-5 text-green-600 flex-shrink-0"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                  <p className="text-sm text-green-800 font-medium">
                    Password changed successfully.
                  </p>
                </div>
                <div className="flex gap-3">
                  <button
                    onClick={() => setSuccess(false)}
                    className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50"
                  >
                    Change Again
                  </button>
                  <button
                    onClick={() => {
                      const role = useAuthStore.getState().user?.role ?? ''
                      const target = role === 'doctor' ? '/doctor/consultation' : role === 'nurse' ? '/nurse/vitals' : role === 'pharmacist' ? '/pharmacy' : role === 'lab_technician' ? '/lab' : '/dashboard'
                      navigate(target, { replace: true })
                    }}
                    className="flex-1 px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90"
                  >
                    Continue
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
                {/* Current password */}
                <div className="space-y-1">
                  <label className="block text-sm font-medium text-gray-700">
                    Current Password
                  </label>
                  <input
                    {...register('current_password')}
                    type="password"
                    autoComplete="current-password"
                    className={inputCls}
                    placeholder="Your current password"
                  />
                  {errors.current_password && (
                    <p className="text-xs text-red-500">{errors.current_password.message}</p>
                  )}
                </div>

                <hr className="border-gray-100" />

                {/* New password */}
                <div className="space-y-1">
                  <label className="block text-sm font-medium text-gray-700">New Password</label>
                  <input
                    {...register('new_password')}
                    type="password"
                    autoComplete="new-password"
                    className={inputCls}
                    placeholder="At least 8 characters"
                  />
                  {errors.new_password && (
                    <p className="text-xs text-red-500">{errors.new_password.message}</p>
                  )}
                </div>

                {/* Confirm password */}
                <div className="space-y-1">
                  <label className="block text-sm font-medium text-gray-700">
                    Confirm New Password
                  </label>
                  <input
                    {...register('confirm_password')}
                    type="password"
                    autoComplete="new-password"
                    className={inputCls}
                    placeholder="Repeat new password"
                  />
                  {errors.confirm_password && (
                    <p className="text-xs text-red-500">{errors.confirm_password.message}</p>
                  )}
                </div>

                {serverError && (
                  <p className="text-xs text-red-500 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                    {serverError}
                  </p>
                )}

                <div className="flex justify-end gap-3 pt-2">
                  <button
                    type="button"
                    onClick={() => navigate(-1)}
                    className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isSubmitting}
                    className="px-5 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
                  >
                    {isSubmitting ? 'Saving…' : 'Update Password'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
