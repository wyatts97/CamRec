export type ThemeName = 'light' | 'dark' | 'darker'

export interface Oklch {
  l: number
  c: number
  h: number
}

export interface AccentTokens {
  primary: string
  primaryForeground: string
  primaryBorder: string
  primaryInk: string
}

export interface AccentPreset {
  key: string
  label: string
  /** The accent colour, or null for the theme default. */
  color: string | null
  swatch: string
}

export const THEME_SURFACES: Record<ThemeName, { card: string; background: string }>
export const LIGHT_LABEL: string
export const DARK_LABEL: string
export const ACCENT_PRESETS: AccentPreset[]

export function parseColor(input: string): Oklch
export function formatOklch(color: Oklch): string
export function toGamut(color: Oklch): Oklch
export function luminance(input: string | Oklch): number
export function contrast(a: string | Oklch, b: string | Oklch): number
export function accentTokens(input: string, theme: ThemeName): AccentTokens
export function accentTokensAllThemes(input: string): Record<ThemeName, AccentTokens>
