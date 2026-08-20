import { useEffect } from 'react'
import { useAuthStore } from '@/features/auth/authStore'

const HEX_COLOR = /^#[0-9a-f]{6}$/i

function hexToHsl(hex: string): string | null {
  if (!HEX_COLOR.test(hex)) return null
  const r = parseInt(hex.slice(1, 3), 16) / 255
  const g = parseInt(hex.slice(3, 5), 16) / 255
  const b = parseInt(hex.slice(5, 7), 16) / 255
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const lightness = (max + min) / 2
  if (max === min) return `0 0% ${Math.round(lightness * 100)}%`
  const delta = max - min
  const saturation = lightness > 0.5 ? delta / (2 - max - min) : delta / (max + min)
  let hue = 0
  if (max === r) hue = (g - b) / delta + (g < b ? 6 : 0)
  else if (max === g) hue = (b - r) / delta + 2
  else hue = (r - g) / delta + 4
  hue /= 6
  return `${Math.round(hue * 360)} ${Math.round(saturation * 100)}% ${Math.round(lightness * 100)}%`
}

export default function TenantBranding() {
  const user = useAuthStore(s => s.user)

  useEffect(() => {
    const root = document.documentElement
    const primary = user?.role === 'super_admin' ? null : hexToHsl(user?.primaryColor ?? '')
    const secondary = user?.role === 'super_admin' ? null : hexToHsl(user?.secondaryColor ?? '')
    root.style.setProperty('--primary', primary ?? '221.2 83.2% 53.3%')
    root.style.setProperty('--ring', primary ?? '221.2 83.2% 53.3%')
    root.style.setProperty('--secondary', secondary ?? '210 40% 96.1%')
    root.style.setProperty('--accent', secondary ?? '210 40% 96.1%')
    return () => {
      root.style.removeProperty('--primary')
      root.style.removeProperty('--ring')
      root.style.removeProperty('--secondary')
      root.style.removeProperty('--accent')
    }
  }, [user?.role, user?.primaryColor, user?.secondaryColor])

  return null
}