#!/usr/bin/env node
/**
 * Fails the build if theme text/control colours drop below WCAG contrast.
 *
 * Parses src/styles/themes.css, resolves each theme's tokens the way the
 * cascade does (<html data-theme="dark"> matches both the :root light block
 * and the dark blocks, so later blocks override earlier ones), then checks the
 * pairs below. Accent presets are checked through the same accentTokens()
 * the app uses at runtime.
 *
 * Usage: node scripts/check-contrast.mjs [--verbose]
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  ACCENT_PRESETS,
  THEME_SURFACES,
  accentTokens,
  contrast,
  parseColor,
  toGamut,
  formatOklch,
} from '../src/lib/color.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const css = readFileSync(resolve(here, '../src/styles/themes.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
const verbose = process.argv.includes('--verbose')

/* ------------------------------------------------------------ parse blocks */

const blocks = []
for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
  const selectors = m[1].split(',').map((s) => s.trim().replace(/"/g, "'"))
  const vars = {}
  for (const d of m[2].matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) vars[d[1]] = d[2].trim()
  blocks.push({ selectors, vars })
}

function tokensFor(theme) {
  const applies = (sel) =>
    sel === ':root' || sel === '[data-theme]' || sel === `[data-theme='${theme}']`
  const vars = {}
  for (const b of blocks) if (b.selectors.some(applies)) Object.assign(vars, b.vars)
  return vars
}

function resolveToken(vars, name, seen = new Set()) {
  if (seen.has(name)) throw new Error(`Cycle resolving ${name}`)
  seen.add(name)
  const raw = vars[name]
  if (raw === undefined) throw new Error(`Undefined token ${name}`)
  return raw.replace(/var\((--[\w-]+)\)/g, (_, ref) => resolveToken(vars, ref, new Set(seen)))
}

/* ----------------------------------------------------------------- helpers */

/** color-mix(in oklab, fg p%, bg) for the translucent badge backgrounds. */
function mixOklab(fg, bg, weight) {
  const lab = (c) => {
    const { l, c: ch, h } = toGamut(parseColor(c))
    return [l, ch * Math.cos((h * Math.PI) / 180), ch * Math.sin((h * Math.PI) / 180)]
  }
  const [a, b] = [lab(fg), lab(bg)]
  const [l, x, y] = a.map((v, i) => v * weight + b[i] * (1 - weight))
  let h = (Math.atan2(y, x) * 180) / Math.PI
  if (h < 0) h += 360
  return formatOklch({ l, c: Math.hypot(x, y), h })
}

const TEXT = 4.5
const UI = 3
const results = []
const check = (theme, label, fg, bg, min) => {
  const ratio = contrast(fg, bg)
  results.push({ theme, label, ratio, min, ok: ratio >= min })
}

/* ------------------------------------------------------------------ checks */

for (const theme of ['light', 'dark', 'darker']) {
  const vars = tokensFor(theme)
  const t = (name) => resolveToken(vars, name)

  const surfaces = { page: t('--background'), card: t('--card'), raised: t('--popover') }
  for (const [role, name] of [['foreground', '--foreground'], ['muted', '--muted'], ['dimmed', '--dimmed']]) {
    for (const [s, bg] of Object.entries(surfaces)) check(theme, `${role} on ${s}`, t(name), bg, TEXT)
  }
  check(theme, 'muted on secondary', t('--muted'), t('--secondary'), TEXT)
  check(theme, 'foreground on input', t('--foreground'), t('--input'), TEXT)

  for (const role of ['primary', 'secondary', 'tertiary', 'danger', 'success', 'warning', 'info']) {
    check(theme, `${role}-foreground on ${role}`, t(`--${role}-foreground`), t(`--${role}`), TEXT)
  }
  check(theme, 'primary-ink on card', t('--primary-ink'), t('--card'), TEXT)
  check(theme, 'primary-ink on page', t('--primary-ink'), t('--background'), TEXT)
  check(theme, 'primary ring vs card', t('--primary'), t('--card'), UI)

  for (const role of ['danger', 'success', 'warning', 'info']) {
    check(theme, `${role} text on card`, t(`--${role}`), t('--card'), TEXT)
    check(theme, `${role} text on page`, t(`--${role}`), t('--background'), TEXT)
    // Status labels also sit on raised rows (bg-secondary), e.g. Settings.
    check(theme, `${role} text on secondary`, t(`--${role}`), t('--secondary'), TEXT)
    // Selia badges: text-{role} on bg-{role}/15 over a card.
    check(theme, `${role} badge (15% tint)`, t(`--${role}`), mixOklab(t(`--${role}`), t('--card'), 0.15), TEXT)
  }

  // Soft separation thresholds: visible, not heavy.
  check(theme, 'input-border vs card', t('--input-border'), t('--card'), 1.8)
  check(theme, 'card vs page', t('--card'), t('--background'), theme === 'darker' ? 1.06 : 1.07)

  // Keep color.mjs's surface table honest: accent inks are computed against it.
  for (const key of ['card', 'background']) {
    const drift = contrast(THEME_SURFACES[theme][key], t(`--${key}`))
    if (drift > 1.01) {
      results.push({ theme, label: `THEME_SURFACES.${key} matches CSS`, ratio: drift, min: 1, ok: false })
    }
  }

  for (const preset of ACCENT_PRESETS.filter((p) => p.color)) {
    const k = accentTokens(preset.color, theme)
    check(theme, `accent ${preset.key}: label`, k.primaryForeground, k.primary, TEXT)
    check(theme, `accent ${preset.key}: ink on card`, k.primaryInk, t('--card'), TEXT)
    check(theme, `accent ${preset.key}: ink on page`, k.primaryInk, t('--background'), TEXT)
  }
}

/* ------------------------------------------------------------------ report */

const failures = results.filter((r) => !r.ok)
const rows = verbose ? results : failures
for (const r of rows) {
  const mark = r.ok ? 'ok  ' : 'FAIL'
  console.log(`${mark} ${r.theme.padEnd(6)} ${r.label.padEnd(34)} ${r.ratio.toFixed(2).padStart(5)} (min ${r.min})`)
}
const worst = (theme) =>
  results.filter((r) => r.theme === theme && r.min === TEXT).reduce((a, r) => (r.ratio < a.ratio ? r : a))
for (const theme of ['light', 'dark', 'darker']) {
  const w = worst(theme)
  console.log(`${theme.padEnd(6)} lowest text pair: ${w.label} ${w.ratio.toFixed(2)}`)
}
if (failures.length) {
  console.error(`\ncheck-contrast: ${failures.length} of ${results.length} checks failed`)
  process.exit(1)
}
console.log(`check-contrast: all ${results.length} checks passed`)
