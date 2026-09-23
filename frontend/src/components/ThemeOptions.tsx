import { Check } from 'lucide-react'
import { useTheme, type ThemeChoice } from '@/hooks/useTheme'
import type { ThemeName } from '@/lib/color.mjs'
import { cn } from '@/lib/utils'

const OPTIONS: { value: ThemeChoice; label: string; hint: string }[] = [
  { value: 'system', label: 'System', hint: 'Match your device' },
  { value: 'light', label: 'Light', hint: 'Bright and airy' },
  { value: 'dark', label: 'Dark', hint: 'Soft grey' },
  { value: 'darker', label: 'Darker', hint: 'True black' },
]

/**
 * A tiny page rendered in a real theme. `data-theme` scopes the theme tokens
 * to this element, so the preview is painted by the same CSS as the app,
 * including the current accent.
 */
function Preview({ theme, className }: { theme: ThemeName; className?: string }) {
  return (
    <div
      data-theme={theme}
      className={cn(theme !== 'light' && 'dark', 'bg-background p-2.5 flex items-end', className)}
      aria-hidden="true"
    >
      <div className="w-full rounded-md bg-card ring ring-card-border p-2 space-y-1.5 shadow-card">
        <div className="h-1.5 w-3/4 rounded-full bg-foreground" />
        <div className="h-1.5 w-1/2 rounded-full bg-muted" />
        <div className="flex items-center gap-1.5 pt-0.5">
          <div className="h-3.5 w-9 rounded bg-primary" />
          <div className="h-1.5 w-6 rounded-full bg-primary-ink" />
        </div>
      </div>
    </div>
  )
}

export default function ThemeOptions() {
  const { theme, setTheme } = useTheme()

  return (
    <div role="radiogroup" aria-label="Theme" className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {OPTIONS.map((option) => {
        const selected = theme === option.value
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => setTheme(option.value)}
            className={cn(
              'group text-left rounded-xl p-1 ring transition-shadow',
              'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
              selected ? 'ring-2 ring-primary' : 'ring-border hover:ring-input-accent-border',
            )}
          >
            <div className="relative h-24 overflow-hidden rounded-lg">
              {option.value === 'system' ? (
                <div className="grid grid-cols-2 h-full">
                  <Preview theme="light" className="h-full" />
                  <Preview theme="dark" className="h-full" />
                </div>
              ) : (
                <Preview theme={option.value} className="h-full" />
              )}
              {selected && (
                <span className="absolute top-1.5 right-1.5 flex size-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
                  <Check className="size-3.5" strokeWidth={3} />
                </span>
              )}
            </div>
            <div className="px-1.5 pt-2 pb-1">
              <p className="text-sm font-medium text-foreground">{option.label}</p>
              <p className="text-xs text-dimmed">{option.hint}</p>
            </div>
          </button>
        )
      })}
    </div>
  )
}
