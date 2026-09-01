import { useEffect } from 'react'
import { useTenantBranding } from '@/hooks/useTenantBranding'
import { generateBrandRamp, hslToCssValue, hexToHslColor } from '@/lib/colorTheme'

export default function TenantBranding() {
  const { primaryColor, secondaryColor } = useTenantBranding()

  useEffect(() => {
    const root = document.documentElement
    const ramp = primaryColor ? generateBrandRamp(primaryColor) : null
    const secondaryHsl = secondaryColor ? hexToHslColor(secondaryColor) : null
    const secondary = secondaryHsl ? hslToCssValue(secondaryHsl) : null
    root.style.setProperty('--primary', ramp?.base ?? '221.2 83.2% 53.3%')
    root.style.setProperty('--primary-tint', ramp?.tint ?? '221.2 83.2% 96%')
    root.style.setProperty('--primary-strong', ramp?.strong ?? '221.2 83.2% 43.3%')
    root.style.setProperty('--ring', ramp?.base ?? '221.2 83.2% 53.3%')
    root.style.setProperty('--secondary', secondary ?? '210 40% 96.1%')
    root.style.setProperty('--accent', secondary ?? '210 40% 96.1%')
    return () => {
      root.style.removeProperty('--primary')
      root.style.removeProperty('--primary-tint')
      root.style.removeProperty('--primary-strong')
      root.style.removeProperty('--ring')
      root.style.removeProperty('--secondary')
      root.style.removeProperty('--accent')
    }
  }, [primaryColor, secondaryColor])

  return null
}