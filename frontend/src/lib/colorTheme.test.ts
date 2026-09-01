import { describe, expect, it } from 'vitest'
import {
  contrastRatio,
  generateBrandRamp,
  generateSuggestedPalettes,
  hexToHslColor,
  hslToCssValue,
  hslToHex,
} from './colorTheme'

describe('hexToHslColor / hslToHex round-trip', () => {
  it('parses known hex colors into HSL', () => {
    expect(hexToHslColor('#ff0000')).toEqual({ h: 0, s: 100, l: 50 })
    expect(hexToHslColor('#ffffff')).toEqual({ h: 0, s: 0, l: 100 })
    expect(hexToHslColor('#000000')).toEqual({ h: 0, s: 0, l: 0 })
  })

  it('returns null for invalid hex input', () => {
    expect(hexToHslColor('not-a-color')).toBeNull()
    expect(hexToHslColor('#fff')).toBeNull()
  })

  it('round-trips hex -> hsl -> hex within rounding tolerance', () => {
    // hexToHslColor rounds h/s/l to whole numbers, so the round trip can be
    // off by a shade per RGB channel — assert closeness, not exact equality.
    const original = '#2563eb'
    const hsl = hexToHslColor(original)
    expect(hsl).not.toBeNull()
    const roundTripped = hslToHex(hsl!)
    const toRgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
    const [r1, g1, b1] = toRgb(original)
    const [r2, g2, b2] = toRgb(roundTripped)
    expect(Math.abs(r1 - r2)).toBeLessThanOrEqual(2)
    expect(Math.abs(g1 - g2)).toBeLessThanOrEqual(2)
    expect(Math.abs(b1 - b2)).toBeLessThanOrEqual(2)
  })
})

describe('hslToCssValue', () => {
  it('formats as space-separated CSS custom-property value', () => {
    expect(hslToCssValue({ h: 221, s: 83, l: 53 })).toBe('221 83% 53%')
  })
})

describe('generateBrandRamp', () => {
  it('produces a tint lighter than base and a strong shade darker than base', () => {
    const ramp = generateBrandRamp('#2563eb')
    expect(ramp).not.toBeNull()
    const base = hexToHslColor('#2563eb')!
    const tint = ramp!.tint.split(' ')
    const strong = ramp!.strong.split(' ')
    const tintLightness = parseFloat(tint[2])
    const strongLightness = parseFloat(strong[2])
    expect(tintLightness).toBeGreaterThan(base.l)
    expect(strongLightness).toBeLessThan(base.l)
  })

  it('returns null for an invalid hex', () => {
    expect(generateBrandRamp('nonsense')).toBeNull()
  })
})

describe('contrastRatio', () => {
  it('matches known WCAG reference ratios', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 0)
    expect(contrastRatio('#ffffff', '#ffffff')).toBeCloseTo(1, 5)
  })
})

describe('generateSuggestedPalettes', () => {
  it('returns palettes with primary/secondary/contrast shape', () => {
    const palettes = generateSuggestedPalettes('#2563eb')
    expect(palettes.length).toBeGreaterThan(0)
    for (const palette of palettes) {
      expect(palette.primary).toMatch(/^#[0-9a-f]{6}$/i)
      expect(palette.secondary).toMatch(/^#[0-9a-f]{6}$/i)
      expect(palette.contrastOnWhite).toBeGreaterThanOrEqual(2.5)
    }
  })

  it('filters out washed-out candidates that fail the minimum contrast threshold', () => {
    // A near-white base color should produce zero or very few usable suggestions.
    const palettes = generateSuggestedPalettes('#fefefe')
    for (const palette of palettes) {
      expect(palette.contrastOnWhite).toBeGreaterThanOrEqual(2.5)
    }
  })

  it('returns an empty array for invalid hex input', () => {
    expect(generateSuggestedPalettes('invalid')).toEqual([])
  })
})
