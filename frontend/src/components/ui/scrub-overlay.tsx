import type { CSSProperties } from 'react'

/**
 * Sprite frame shown over a card thumbnail while hover-scrubbing, with a thin
 * progress line along the bottom. Renders nothing when not scrubbing.
 */
export function ScrubOverlay({
  style,
  fraction,
}: {
  style: CSSProperties | null
  fraction: number | null
}) {
  if (!style) return null
  return (
    <div className="absolute inset-0 z-[5] pointer-events-none bg-secondary" style={style} aria-hidden="true">
      {fraction !== null && (
        <div className="absolute inset-x-0 bottom-0 h-0.5 bg-black/40">
          <div className="h-full bg-primary" style={{ width: `${fraction * 100}%` }} />
        </div>
      )}
    </div>
  )
}
