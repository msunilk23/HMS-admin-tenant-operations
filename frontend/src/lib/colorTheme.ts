/**
 * Shared color-theory utilities for tenant theming: hex/HSL/RGB conversion,
 * a light "tint"/"strong" ramp derived from a single brand color, WCAG
 * contrast checking, and deterministic "suggested look" palette generation.
 *
 * Pure functions only — no React/DOM — so both the app-wide theme applier
 * (TenantBranding) and the self-service Branding page (live preview +
 * suggestions) share one implementation.
 */

const HEX_COLOR = /^#[0-9a-f]{6}$/i

export interface HslColor {
  h: number // 0..360
  s: number // 0..100
  l: number // 0..100
}

export function hexToHslColor(hex: string): HslColor | null {
  if (!HEX_COLOR.test(hex)) return null
  const r = parseInt(hex.slice(1, 3), 16) / 255
  const g = parseInt(hex.slice(3, 5), 16) / 255
  const b = parseInt(hex.slice(5, 7), 16) / 255
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const l = (max + min) / 2
  if (max === min) return { h: 0, s: 0, l: Math.round(l * 100) }
  const delta = max - min
  const s = l > 0.5 ? delta / (2 - max - min) : delta / (max + min)
  let h = 0
  if (max === r) h = (g - b) / delta + (g < b ? 6 : 0)
  else if (max === g) h = (b - r) / delta + 2
  else h = (r - g) / delta + 4
  h /= 6
  return { h: Math.round(h * 360), s: Math.round(s * 100), l: Math.round(l * 100) }
}

export function hslToHex({ h, s, l }: HslColor): string {
  const sNorm = s / 100
  const lNorm = l / 100
  const c = (1 - Math.abs(2 * lNorm - 1)) * sNorm
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = lNorm - c / 2
  let [r, g, b] = [0, 0, 0]
  if (h < 60) [r, g, b] = [c, x, 0]
  else if (h < 120) [r, g, b] = [x, c, 0]
  else if (h < 180) [r, g, b] = [0, c, x]
  else if (h < 240) [r, g, b] = [0, x, c]
  else if (h < 300) [r, g, b] = [x, 0, c]
  else [r, g, b] = [c, 0, x]
  const toHex = (channel: number) => Math.round((channel + m) * 255).toString(16).padStart(2, '0')
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`
}

/** CSS custom-property value, e.g. "221.2 83.2% 53.3%" (space-separated, no hsl() wrapper). */
export function hslToCssValue(hsl: HslColor): string {
  return `${hsl.h} ${hsl.s}% ${hsl.l}%`
}

function clampPercent(value: number): number {
  return Math.min(100, Math.max(0, value))
}

/** Lighten toward white by `amount` (0..1) — used for pale tints and secondary accents. */
function lighten(hsl: HslColor, amount: number): HslColor {
  return { ...hsl, l: clampPercent(hsl.l + (100 - hsl.l) * amount) }
}

function darken(hsl: HslColor, amount: number): HslColor {
  return { ...hsl, l: clampPercent(hsl.l - hsl.l * amount) }
}

export interface BrandRamp {
  tint: string // CSS value — very pale wash, for page/section backgrounds
  base: string // CSS value — the brand color itself, for buttons/links/active states
  strong: string // CSS value — darker, for hover/pressed states
}

/** Derives a background-safe tint + hover-safe "strong" shade from one brand hex color. */
export function generateBrandRamp(hex: string): BrandRamp | null {
  const base = hexToHslColor(hex)
  if (!base) return null
  return {
    tint: hslToCssValue(lighten(base, 0.9)),
    base: hslToCssValue(base),
    strong: hslToCssValue(darken(base, 0.18)),
  }
}

function srgbChannelToLinear(channel: number): number {
  const c = channel / 255
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
}

function relativeLuminance(hex: string): number {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return 0.2126 * srgbChannelToLinear(r) + 0.7152 * srgbChannelToLinear(g) + 0.0722 * srgbChannelToLinear(b)
}

/** WCAG contrast ratio (1..21) between two hex colors. */
export function contrastRatio(hexA: string, hexB: string): number {
  const lumA = relativeLuminance(hexA)
  const lumB = relativeLuminance(hexB)
  const lighter = Math.max(lumA, lumB)
  const darker = Math.min(lumA, lumB)
  return (lighter + 0.05) / (darker + 0.05)
}

export interface SuggestedPalette {
  id: string
  label: string
  description: string
  primary: string
  secondary: string
  /** Contrast ratio of the primary color against a white background (buttons/badges). */
  contrastOnWhite: number
}

interface PaletteRecipe {
  id: string
  label: string
  description: string
  hueShift: number
  saturationShift: number
}

const PALETTE_RECIPES: PaletteRecipe[] = [
  {
    id: 'as-extracted',
    label: 'As Extracted',
    description: 'Straight from your uploaded logo — the truest match to your brand.',
    hueShift: 0,
    saturationShift: 0,
  },
  {
    id: 'complementary',
    label: 'Complementary Contrast',
    description: 'A bold, contrasting accent for a vibrant, energetic feel.',
    hueShift: 180,
    saturationShift: 0,
  },
  {
    id: 'analogous-calm',
    label: 'Analogous Calm',
    description: 'A softer neighboring hue — calmer and more clinical in tone.',
    hueShift: 30,
    saturationShift: -15,
  },
]

/** Minimum contrast (against white) for a color to be usable as a button/accent. */
const MIN_USABLE_CONTRAST = 2.5

/**
 * Deterministic (non-LLM) "suggested looks" derived from one extracted brand
 * color via standard color-theory hue rotations. Filters out any candidate
 * too washed-out to read as a UI accent against a white background.
 */
export function generateSuggestedPalettes(primaryHex: string): SuggestedPalette[] {
  const base = hexToHslColor(primaryHex)
  if (!base) return []

  return PALETTE_RECIPES.map((recipe) => {
    const primaryHsl: HslColor = {
      h: (base.h + recipe.hueShift + 360) % 360,
      s: clampPercent(base.s + recipe.saturationShift),
      l: base.l,
    }
    const secondaryHsl = lighten(primaryHsl, 0.85)
    const primaryOut = hslToHex(primaryHsl)
    return {
      id: recipe.id,
      label: recipe.label,
      description: recipe.description,
      primary: primaryOut,
      secondary: hslToHex(secondaryHsl),
      contrastOnWhite: contrastRatio(primaryOut, '#ffffff'),
    }
  }).filter((palette) => palette.contrastOnWhite >= MIN_USABLE_CONTRAST)
}
