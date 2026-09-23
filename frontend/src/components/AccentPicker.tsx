import { useMemo } from 'react'
import { Check } from 'lucide-react'
import { ACCENT_PRESETS, accentColor, useTheme } from '@/hooks/useTheme'
import { accentTokens } from '@/lib/color.mjs'
import { cn } from '@/lib/utils'

/**
 * Accent colour picker. Overrides the theme's primary colour with a preset or
 * any custom colour; label and text shades are derived automatically so every
 * choice stays readable (see accentTokens in src/lib/color.mjs).
 */
export default function AccentPicker() {
  const { accent, setAccent, resolvedTheme } = useTheme()

  const isCustom = !ACCENT_PRESETS.some((p) => p.key === accent)
  // <input type="color"> only accepts hex.
  const customValue = isCustom && accent.startsWith('#') ? accent : '#7c3aed'

  // Check-mark colour per swatch: the same label colour the buttons get.
  const checkColor = useMemo(() => {
    const colors: Record<string, string> = {}
    for (const preset of ACCENT_PRESETS) {
      colors[preset.key] = accentTokens(preset.color ?? preset.swatch, resolvedTheme).primaryForeground
    }
    return colors
  }, [resolvedTheme])

  const customCheck = useMemo(() => {
    const color = accentColor(accent)
    try {
      return color ? accentTokens(color, resolvedTheme).primaryForeground : undefined
    } catch {
      return undefined
    }
  }, [accent, resolvedTheme])

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm font-medium text-foreground">Accent color</p>
        {/* Live sample, painted with the resolved tokens. */}
        <div className="flex items-center gap-3" aria-hidden="true">
          <span className="inline-flex h-7 items-center rounded-md bg-primary px-2.5 text-xs font-medium text-primary-foreground">
            Button
          </span>
          <span className="text-sm font-medium text-primary-ink underline underline-offset-2">Link</span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2.5" role="radiogroup" aria-label="Accent color">
        {ACCENT_PRESETS.map((preset) => {
          const active = accent === preset.key
          return (
            <button
              key={preset.key}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => setAccent(preset.key)}
              aria-label={`${preset.label} accent`}
              title={preset.label}
              className={cn(
                'relative h-8 w-8 rounded-full transition-transform hover:scale-110 motion-reduce:hover:scale-100',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:ring-foreground/40',
                active && 'ring-2 ring-offset-2 ring-offset-background ring-foreground/60',
              )}
              style={{ backgroundColor: preset.swatch }}
            >
              {active && (
                <Check
                  className="absolute inset-0 m-auto h-4 w-4"
                  strokeWidth={3}
                  style={{ color: checkColor[preset.key] }}
                />
              )}
            </button>
          )
        })}

        {/* Custom colour */}
        <label
          className={cn(
            'relative h-8 w-8 rounded-full cursor-pointer transition-transform hover:scale-110 motion-reduce:hover:scale-100 overflow-hidden',
            'ring-1 ring-border',
            isCustom && 'ring-2 ring-offset-2 ring-offset-background ring-foreground/60',
          )}
          title="Custom color"
          style={{
            background: isCustom
              ? customValue
              : 'conic-gradient(from 0deg, #ef4444, #f59e0b, #22c55e, #3b82f6, #a855f7, #ef4444)',
          }}
        >
          <input
            type="color"
            value={customValue}
            onChange={(e) => setAccent(e.target.value)}
            aria-label="Custom accent color"
            className="absolute inset-0 opacity-0 cursor-pointer"
          />
          {isCustom && (
            <Check
              className="absolute inset-0 m-auto h-4 w-4 pointer-events-none"
              strokeWidth={3}
              style={{ color: customCheck }}
            />
          )}
        </label>
      </div>
      <p className="text-xs text-muted">
        Used for buttons, links and active states. Text on it switches between light and dark automatically so it stays
        readable.
      </p>
    </div>
  )
}
