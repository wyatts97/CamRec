/**
 * Colour maths shared by the app (accent tokens) and scripts/check-contrast.mjs.
 *
 * Plain ES module with a .d.mts sibling so Node can run it directly in the
 * build (no TS loader) while the app still imports it with types.
 */

/** Surface colours the accent "ink" must stay readable on, per theme. Must
 *  match src/styles/themes.css; check-contrast.mjs fails the build if the CSS
 *  drifts so that a computed ink no longer passes. */
export const THEME_SURFACES = {
  light: { card: 'oklch(1 0 0)', background: 'oklch(0.97 0.003 248)' },
  dark: { card: 'oklch(0.26 0.005 248)', background: 'oklch(0.22 0.005 248)' },
  darker: { card: 'oklch(0.155 0.004 248)', background: 'oklch(0 0 0)' },
}

export const LIGHT_LABEL = 'oklch(0.985 0.002 248)'
export const DARK_LABEL = 'oklch(0.18 0.004 248)'

/** Built-in accent presets. `default` clears any override (theme blue). */
export const ACCENT_PRESETS = [
  { key: 'default', label: 'Default', color: null, swatch: 'oklch(0.55 0.2 263)' },
  { key: 'violet', label: 'Violet', color: 'oklch(0.561 0.2456 302.32)' },
  { key: 'pink', label: 'Pink', color: 'oklch(0.6559 0.2118 354.31)' },
  { key: 'rose', label: 'Rose', color: 'oklch(0.6368 0.2078 25.33)' },
  { key: 'orange', label: 'Orange', color: 'oklch(0.7049 0.1867 47.6)' },
  { key: 'emerald', label: 'Emerald', color: 'oklch(0.6959 0.1491 162.48)' },
  { key: 'teal', label: 'Teal', color: 'oklch(0.7045 0.1234 182.5)' },
].map((p) => ({ ...p, swatch: p.swatch ?? p.color }))

const THEMES = ['light', 'dark', 'darker']

/* ---------------------------------------------------------------- parsing */

/** Parse `oklch(L C H [/ a])` (L as 0-1 or %) or `#rgb`/`#rrggbb` into {l,c,h}. */
export function parseColor(input) {
  const value = String(input).trim().toLowerCase()
  const ok = value.match(/^oklch\(\s*([\d.]+)(%?)\s+([\d.]+)\s+([\d.]+)(?:deg)?\s*(?:\/\s*[\d.%]+\s*)?\)$/)
  if (ok) {
    const l = parseFloat(ok[1]) / (ok[2] ? 100 : 1)
    return { l, c: parseFloat(ok[3]), h: parseFloat(ok[4]) }
  }
  const hex = value.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/)
  if (hex) {
    let h = hex[1]
    if (h.length === 3) h = h.split('').map((ch) => ch + ch).join('')
    const srgb = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
    return linearRgbToOklch(srgb.map(srgbToLinear))
  }
  throw new Error(`Unsupported colour: ${input}`)
}

export function formatOklch({ l, c, h }) {
  const r = (n, d) => Number(n.toFixed(d))
  return `oklch(${r(l, 4)} ${r(c, 4)} ${r(h, 2)})`
}

/* ------------------------------------------------------------ conversions */

function srgbToLinear(v) {
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
}

function linearRgbToOklch([r, g, b]) {
  const l_ = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m_ = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s_ = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  const L = 0.2104542553 * l_ + 0.793617785 * m_ - 0.0040720468 * s_
  const A = 1.9779984951 * l_ - 2.428592205 * m_ + 0.4505937099 * s_
  const B = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.808675766 * s_
  const c = Math.sqrt(A * A + B * B)
  let h = (Math.atan2(B, A) * 180) / Math.PI
  if (h < 0) h += 360
  return { l: L, c, h }
}

/** OKLCH -> linear sRGB (unclamped). */
function oklchToLinearRgb({ l, c, h }) {
  const a = c * Math.cos((h * Math.PI) / 180)
  const b = c * Math.sin((h * Math.PI) / 180)
  const l_ = l + 0.3963377774 * a + 0.2158037573 * b
  const m_ = l - 0.1055613458 * a - 0.0638541728 * b
  const s_ = l - 0.0894841775 * a - 1.291485548 * b
  const L = l_ ** 3
  const M = m_ ** 3
  const S = s_ ** 3
  return [
    4.0767416621 * L - 3.3077115913 * M + 0.2309699292 * S,
    -1.2684380046 * L + 2.6097574011 * M - 0.3413193965 * S,
    -0.0041960863 * L - 0.7034186147 * M + 1.707614701 * S,
  ]
}

const inGamut = (rgb) => rgb.every((v) => v >= -1e-4 && v <= 1 + 1e-4)

/** Reduce chroma until the colour fits in sRGB (what the browser shows). */
export function toGamut(color) {
  let { l, c, h } = color
  l = Math.min(1, Math.max(0, l))
  if (inGamut(oklchToLinearRgb({ l, c, h }))) return { l, c, h }
  let lo = 0
  let hi = c
  for (let i = 0; i < 24; i++) {
    const mid = (lo + hi) / 2
    if (inGamut(oklchToLinearRgb({ l, c: mid, h }))) lo = mid
    else hi = mid
  }
  return { l, c: lo, h }
}

/** WCAG relative luminance of a colour (string or {l,c,h}). */
export function luminance(input) {
  const color = toGamut(typeof input === 'string' ? parseColor(input) : input)
  const [r, g, b] = oklchToLinearRgb(color).map((v) => Math.min(1, Math.max(0, v)))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** WCAG 2.x contrast ratio between two colours. */
export function contrast(a, b) {
  const la = luminance(a)
  const lb = luminance(b)
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

/* ---------------------------------------------------------------- accents */

const INK_TARGET = 4.6 // a little headroom over AA 4.5

/**
 * Derive readable tokens from an accent colour for one theme.
 *
 * - primary: the accent exactly as chosen (button fills, rings, borders)
 * - primaryForeground: near-white or near-black, whichever reads better on it
 * - primaryBorder: one step darker
 * - primaryInk: the accent's hue/chroma at a lightness that passes as text on
 *   the theme's card and page (links, active labels)
 */
export function accentTokens(input, theme) {
  const base = toGamut(parseColor(input))
  const surfaces = THEME_SURFACES[theme]
  const light = contrast(LIGHT_LABEL, base)
  const dark = contrast(DARK_LABEL, base)

  const passes = (l) => {
    const ink = toGamut({ ...base, l })
    return (
      contrast(ink, surfaces.card) >= INK_TARGET &&
      contrast(ink, surfaces.background) >= INK_TARGET
    )
  }
  let inkL = base.l
  if (!passes(inkL)) {
    // Light surfaces need a darker ink, dark surfaces a lighter one.
    const step = theme === 'light' ? -0.01 : 0.01
    while (!passes(inkL) && inkL > 0 && inkL < 1) inkL += step
  }

  return {
    primary: formatOklch(base),
    primaryForeground: light >= dark ? LIGHT_LABEL : DARK_LABEL,
    primaryBorder: formatOklch(toGamut({ ...base, l: Math.max(0, base.l - 0.05) })),
    primaryInk: formatOklch(toGamut({ ...base, l: inkL })),
  }
}

/** Accent tokens for every theme, for the pre-paint cache. */
export function accentTokensAllThemes(input) {
  return Object.fromEntries(THEMES.map((t) => [t, accentTokens(input, t)]))
}
