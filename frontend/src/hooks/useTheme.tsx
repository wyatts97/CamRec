import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import {
  ACCENT_PRESETS,
  accentTokensAllThemes,
  type AccentPreset,
  type AccentTokens,
  type ThemeName,
} from '@/lib/color.mjs'

export { ACCENT_PRESETS }
export type { AccentPreset }

/** What the user picked. `system` follows the OS light/dark preference. */
export type ThemeChoice = 'system' | ThemeName
export type ResolvedTheme = ThemeName

// Storage keys are shared with the pre-paint script in index.html.
const THEME_KEY = 'camsuite-theme'
const ACCENT_KEY = 'camsuite-accent'
const ACCENT_CSS_KEY = 'camsuite-accent-css'
const ACCENT_STYLE_ID = 'camsuite-accent'

/** Browser chrome colour per theme (hex of each theme's --background). */
const THEME_COLOR: Record<ResolvedTheme, string> = {
  light: '#f3f5f7',
  dark: '#191b1d',
  darker: '#000000',
}

const THEME_CHOICES: ThemeChoice[] = ['system', 'light', 'dark', 'darker']

interface ThemeContextValue {
  theme: ThemeChoice
  resolvedTheme: ResolvedTheme
  setTheme: (theme: ThemeChoice) => void
  accent: string
  setAccent: (accent: string) => void
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: 'system',
  resolvedTheme: 'light',
  setTheme: () => {},
  accent: 'default',
  setAccent: () => {},
})

function safeGet(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function safeSet(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    /* Storage unavailable: preferences just won't persist. */
  }
}

function readStoredTheme(): ThemeChoice {
  const stored = safeGet(THEME_KEY)
  // "Neo-Futurism" was renamed "Darker".
  if (stored === 'neo-futurism') {
    safeSet(THEME_KEY, 'darker')
    return 'darker'
  }
  return THEME_CHOICES.includes(stored as ThemeChoice) ? (stored as ThemeChoice) : 'system'
}

function systemTheme(): ResolvedTheme {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function applyTheme(resolved: ResolvedTheme) {
  const root = document.documentElement
  root.dataset.theme = resolved
  root.classList.toggle('dark', resolved !== 'light')
  root.classList.remove('light')
  let meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (!meta) {
    meta = document.createElement('meta')
    meta.name = 'theme-color'
    document.head.appendChild(meta)
  }
  meta.content = THEME_COLOR[resolved]
}

/**
 * CSS for an accent override. A stylesheet rather than inline properties on
 * <html>: nested `data-theme` elements (the Settings previews) re-declare the
 * theme tokens, which would shadow inline values. `html [data-theme]` also
 * out-specifies the theme blocks regardless of stylesheet order.
 */
function accentCss(tokens: Record<ResolvedTheme, AccentTokens>): string {
  return (Object.keys(tokens) as ResolvedTheme[])
    .map((theme) => {
      const t = tokens[theme]
      return (
        `html[data-theme='${theme}'],html [data-theme='${theme}']{` +
        `--primary:${t.primary};--primary-foreground:${t.primaryForeground};` +
        `--primary-border:${t.primaryBorder};--primary-ink:${t.primaryInk}}`
      )
    })
    .join('')
}

/** Resolve an accent key (preset key or raw hex) to its colour, or null. */
export function accentColor(accent: string): string | null {
  const preset = ACCENT_PRESETS.find((p) => p.key === accent)
  if (preset) return preset.color
  return accent && accent !== 'default' ? accent : null
}

function applyAccent(accent: string) {
  const root = document.documentElement
  // Clean up inline overrides written by earlier versions.
  for (const prop of ['--primary', '--primary-border']) root.style.removeProperty(prop)
  safeSet('camsuite-accent-resolved', null)

  let style = document.getElementById(ACCENT_STYLE_ID) as HTMLStyleElement | null
  const color = accentColor(accent)
  let css = ''
  if (color) {
    try {
      css = accentCss(accentTokensAllThemes(color))
    } catch {
      css = '' // Unparseable custom colour: fall back to the theme default.
    }
  }
  if (!css) {
    style?.remove()
    safeSet(ACCENT_CSS_KEY, null)
    return
  }
  if (!style) {
    style = document.createElement('style')
    style.id = ACCENT_STYLE_ID
    document.head.appendChild(style)
  }
  style.textContent = css
  // Cached so the pre-paint script applies the accent before first paint.
  safeSet(ACCENT_CSS_KEY, css)
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemeChoice>(readStoredTheme)
  const [system, setSystem] = useState<ResolvedTheme>(systemTheme)
  const [accent, setAccentState] = useState<string>(() => safeGet(ACCENT_KEY) || 'default')

  const resolvedTheme: ResolvedTheme = theme === 'system' ? system : theme

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const listener = (e: MediaQueryListEvent) => setSystem(e.matches ? 'dark' : 'light')
    mq.addEventListener('change', listener)
    return () => mq.removeEventListener('change', listener)
  }, [])

  useEffect(() => applyTheme(resolvedTheme), [resolvedTheme])
  useEffect(() => applyAccent(accent), [accent])

  const setTheme = useCallback((next: ThemeChoice) => {
    safeSet(THEME_KEY, next)
    setThemeState(next)
  }, [])

  const setAccent = useCallback((next: string) => {
    safeSet(ACCENT_KEY, next)
    setAccentState(next)
  }, [])

  const value = useMemo(
    () => ({ theme, resolvedTheme, setTheme, accent, setAccent }),
    [theme, resolvedTheme, setTheme, accent, setAccent],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  return useContext(ThemeContext)
}
