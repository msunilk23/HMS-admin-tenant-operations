/**
 * Self-service hospital branding — logo upload, manual color pickers, a live
 * preview scoped to this page only, and deterministic "suggested look"
 * palettes derived from the current brand color. hospital_admin only.
 */
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Palette, UploadCloud } from 'lucide-react'
import { tenantService } from '@/services/tenantService'
import { generateSuggestedPalettes, hslToCssValue, hexToHslColor, type SuggestedPalette } from '@/lib/colorTheme'

const DEFAULT_PRIMARY = '#2563eb'
const DEFAULT_SECONDARY = '#eff6ff'

type ToastType = 'success' | 'error'

function previewStyle(primary: string, secondary: string): React.CSSProperties {
  const primaryHsl = hexToHslColor(primary)
  const secondaryHsl = hexToHslColor(secondary)
  return {
    '--preview-primary': primaryHsl ? hslToCssValue(primaryHsl) : '221.2 83.2% 53.3%',
    '--preview-secondary': secondaryHsl ? hslToCssValue(secondaryHsl) : '210 40% 96.1%',
  } as React.CSSProperties
}

export default function BrandingPage() {
  const qc = useQueryClient()
  const seeded = useRef(false)
  const [primaryColor, setPrimaryColor] = useState(DEFAULT_PRIMARY)
  const [secondaryColor, setSecondaryColor] = useState(DEFAULT_SECONDARY)
  const [logoUrl, setLogoUrl] = useState<string | null>(null)
  const [toast, setToast] = useState<{ message: string; type: ToastType } | null>(null)

  const branding = useQuery({
    queryKey: ['tenant-branding'],
    queryFn: tenantService.getBranding,
    refetchInterval: false,
  })

  // Seed local editable state from the server exactly once, so the shared
  // 60s background poll (used elsewhere to keep other tabs live) never
  // clobbers colors the admin is actively editing on this page.
  useEffect(() => {
    if (seeded.current || !branding.data) return
    seeded.current = true
    setPrimaryColor(branding.data.primary_color ?? DEFAULT_PRIMARY)
    setSecondaryColor(branding.data.secondary_color ?? DEFAULT_SECONDARY)
    setLogoUrl(branding.data.logo_url)
  }, [branding.data])

  const showToast = (message: string, type: ToastType = 'success') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  const uploadLogo = useMutation({
    mutationFn: (file: File) => tenantService.uploadBrandingLogo(file),
    onSuccess: (result) => {
      setLogoUrl(result.logo_url)
      setPrimaryColor(result.primary_color ?? DEFAULT_PRIMARY)
      setSecondaryColor(result.secondary_color ?? DEFAULT_SECONDARY)
      qc.invalidateQueries({ queryKey: ['tenant-branding'] })
      showToast('Logo uploaded — colors updated from your logo')
    },
    onError: (err: any) => showToast(err?.response?.data?.detail ?? 'Failed to upload logo', 'error'),
  })

  const save = useMutation({
    mutationFn: () => tenantService.updateBranding({ primary_color: primaryColor, secondary_color: secondaryColor }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tenant-branding'] })
      showToast('Branding saved')
    },
    onError: (err: any) => showToast(err?.response?.data?.detail ?? 'Failed to save branding', 'error'),
  })

  const handleLogoFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (file) uploadLogo.mutate(file)
  }

  const suggestions: SuggestedPalette[] = generateSuggestedPalettes(primaryColor)

  const applySuggestion = (palette: SuggestedPalette) => {
    setPrimaryColor(palette.primary)
    setSecondaryColor(palette.secondary)
  }

  if (branding.isLoading) {
    return <div className="p-6" role="status">Loading branding…</div>
  }

  return (
    <div className="p-6 space-y-6 max-w-4xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Hospital Branding</h1>
        <p className="text-sm text-gray-500 mt-1">Your logo and colors apply across the app for every staff account at your hospital.</p>
      </div>

      <section className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
        <h2 className="font-semibold text-gray-900">Logo</h2>
        <div className="flex items-center gap-3">
          {logoUrl && <img src={logoUrl} alt="Hospital logo preview" className="h-12 w-12 rounded-full border border-gray-200 object-cover flex-shrink-0" />}
          <label className="flex-1 cursor-pointer rounded-lg border border-dashed border-gray-300 px-3 py-2 text-center text-sm text-gray-600 hover:bg-gray-50">
            <span className="inline-flex items-center gap-2"><UploadCloud className="h-4 w-4" aria-hidden="true" />{uploadLogo.isPending ? 'Uploading…' : 'Upload PNG, JPEG, or WEBP'}</span>
            <input type="file" accept="image/png,image/jpeg,image/webp" onChange={handleLogoFileChange} disabled={uploadLogo.isPending} className="hidden" />
          </label>
        </div>
        <p className="text-xs text-gray-400">Uploading a logo automatically picks brand colors from it — you can still fine-tune them below.</p>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
        <h2 className="font-semibold text-gray-900">Colors</h2>
        <div className="grid grid-cols-2 gap-4">
          <label className="text-sm font-medium text-gray-700">Primary color
            <input type="color" value={primaryColor} onChange={(e) => setPrimaryColor(e.target.value)} className="mt-1 block h-10 w-full cursor-pointer rounded border border-gray-300 p-1" />
          </label>
          <label className="text-sm font-medium text-gray-700">Secondary color
            <input type="color" value={secondaryColor} onChange={(e) => setSecondaryColor(e.target.value)} className="mt-1 block h-10 w-full cursor-pointer rounded border border-gray-300 p-1" />
          </label>
        </div>

        {/* Live preview scoped to this panel only — does not affect the rest of the app until saved. */}
        <div style={previewStyle(primaryColor, secondaryColor)} className="rounded-lg border border-gray-200 p-4 space-y-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Preview</p>
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-[hsl(var(--preview-secondary))] px-3 py-2 text-sm font-medium text-[hsl(var(--preview-primary))]">Active nav item</div>
            <button type="button" className="rounded-lg bg-[hsl(var(--preview-primary))] px-3 py-2 text-sm font-medium text-white">Primary button</button>
          </div>
        </div>

        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 disabled:opacity-50"
        >
          {save.isPending ? 'Saving…' : 'Save Changes'}
        </button>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2">
          <Palette className="h-5 w-5 text-gray-500" aria-hidden="true" />
          <h2 className="font-semibold text-gray-900">Suggested looks</h2>
        </div>
        <p className="text-xs text-gray-400">Based on your current primary color — pick one to apply it, then Save Changes.</p>
        <div className="grid gap-3 sm:grid-cols-3">
          {suggestions.map((palette) => (
            <button
              key={palette.id}
              type="button"
              onClick={() => applySuggestion(palette)}
              className={`text-left rounded-lg border p-3 hover:border-gray-400 transition-colors ${
                palette.primary.toLowerCase() === primaryColor.toLowerCase() ? 'border-gray-900' : 'border-gray-200'
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="h-6 w-6 rounded-full border border-gray-200" style={{ backgroundColor: palette.primary }} />
                <span className="h-6 w-6 rounded-full border border-gray-200" style={{ backgroundColor: palette.secondary }} />
                {palette.primary.toLowerCase() === primaryColor.toLowerCase() && <Check className="h-4 w-4 text-gray-900" aria-hidden="true" />}
              </div>
              <p className="text-sm font-semibold text-gray-900">{palette.label}</p>
              <p className="text-xs text-gray-500 mt-0.5">{palette.description}</p>
            </button>
          ))}
        </div>
      </section>

      {toast && (
        <div
          role="status"
          className={`fixed bottom-6 right-6 z-50 rounded-lg px-4 py-3 text-sm font-medium text-white shadow-lg ${toast.type === 'success' ? 'bg-green-600' : 'bg-red-600'}`}
        >
          {toast.message}
        </div>
      )}
    </div>
  )
}
