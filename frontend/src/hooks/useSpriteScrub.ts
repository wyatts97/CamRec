import { useCallback, useEffect, useState, type CSSProperties, type PointerEvent } from 'react'
import { useQuery } from '@tanstack/react-query'

export interface SpriteCue {
  start: number
  end: number
  url: string
  x: number
  y: number
  w: number
  h: number
}

function parseTime(value: string): number {
  return value
    .trim()
    .split(':')
    .map(Number)
    .reduce((total, part) => total * 60 + part, 0)
}

/** Parse a WEBVTT sprite map (`sprite#xywh=x,y,w,h` cues) into absolute cues. */
export function parseSpriteVtt(text: string, vttUrl: string): SpriteCue[] {
  const base = new URL(vttUrl, window.location.href)
  const cues: SpriteCue[] = []
  const lines = text.split(/\r?\n/)
  for (let i = 0; i < lines.length; i++) {
    // Only timing lines matter; NOTE blocks and headers never contain "-->".
    const timing = lines[i].match(/^(\S+)\s+-->\s+(\S+)/)
    const ref = lines[i + 1]?.trim()
    if (!timing || !ref) continue
    const [file, hash] = ref.split('#xywh=')
    if (!hash) continue
    const [x, y, w, h] = hash.split(',').map(Number)
    cues.push({
      start: parseTime(timing[1]),
      end: parseTime(timing[2]),
      url: new URL(file, base).toString(),
      x,
      y,
      w,
      h,
    })
  }
  return cues
}

/**
 * The cue shown at `time`: the same rule Vidstack's player uses
 * (start <= time < end), so a card and the player agree on every frame.
 */
export function cueAtTime(cues: SpriteCue[], time: number): SpriteCue | null {
  for (let i = cues.length - 1; i >= 0; i--) {
    const cue = cues[i]
    if (time >= cue.start && time < cue.end) return cue
  }
  if (!cues.length) return null
  // Outside every cue: clamp to the nearest end.
  const last = cues[cues.length - 1]
  return time >= last.end ? last : cues[0]
}

/**
 * Background style that shows one tile of a sprite sheet filling its box.
 * Uses the sheet's real pixel size: ffmpeg's tile filter always lays out a
 * full grid (padding short sheets with blank cells), so the grid can't be
 * inferred from the cues.
 */
export function spriteTileStyle(cue: SpriteCue, sheetWidth: number, sheetHeight: number): CSSProperties {
  const spanX = sheetWidth - cue.w
  const spanY = sheetHeight - cue.h
  return {
    backgroundImage: `url("${cue.url}")`,
    backgroundSize: `${(sheetWidth / cue.w) * 100}% ${(sheetHeight / cue.h) * 100}%`,
    backgroundPosition: `${spanX > 0 ? (cue.x / spanX) * 100 : 0}% ${spanY > 0 ? (cue.y / spanY) * 100 : 0}%`,
  }
}

// Natural size per sheet URL, shared by every card on the page.
const sheetSizes = new Map<string, Promise<{ width: number; height: number }>>()

function loadSheetSize(url: string) {
  let pending = sheetSizes.get(url)
  if (!pending) {
    pending = new Promise((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight })
      img.onerror = () => {
        sheetSizes.delete(url)
        reject(new Error(`sprite sheet failed to load: ${url}`))
      }
      img.src = url
    })
    sheetSizes.set(url, pending)
  }
  return pending
}

/**
 * Hover-scrub preview from a recording's or clip's thumbnail sprite.
 *
 * The VTT and sheet load on first hover (not on mount), so a grid of cards
 * costs nothing until the pointer moves over one. Returns handlers for the
 * card's media area and a style for an absolutely positioned overlay, which is
 * null while not scrubbing so the static thumbnail shows through.
 */
export function useSpriteScrub(vttUrl: string | null) {
  const [hovering, setHovering] = useState(false)
  const [fraction, setFraction] = useState<number | null>(null)
  const [sizes, setSizes] = useState<Record<string, { width: number; height: number }>>({})

  const { data: cues } = useQuery({
    queryKey: ['sprite-vtt', vttUrl],
    queryFn: async () => {
      const res = await fetch(vttUrl!, { credentials: 'include' })
      if (!res.ok) throw new Error(`sprite map ${res.status}`)
      return parseSpriteVtt(await res.text(), vttUrl!)
    },
    enabled: hovering && !!vttUrl,
    staleTime: 5 * 60_000,
    retry: false,
  })

  // Measure each sheet the cues reference (normally exactly one).
  useEffect(() => {
    if (!cues?.length) return
    let cancelled = false
    for (const url of new Set(cues.map((c) => c.url))) {
      loadSheetSize(url)
        .then((size) => {
          if (!cancelled) setSizes((prev) => (prev[url] ? prev : { ...prev, [url]: size }))
        })
        .catch(() => {})
    }
    return () => {
      cancelled = true
    }
  }, [cues])

  const onPointerMove = useCallback((e: PointerEvent<HTMLElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    setFraction(Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)))
  }, [])
  const onPointerEnter = useCallback(() => setHovering(true), [])
  const onPointerLeave = useCallback(() => setFraction(null), [])

  let style: CSSProperties | null = null
  if (fraction !== null && cues?.length) {
    const duration = cues[cues.length - 1].end
    const cue = cueAtTime(cues, fraction * duration)
    const size = cue && sizes[cue.url]
    if (cue && size) style = spriteTileStyle(cue, size.width, size.height)
  }

  return {
    handlers: vttUrl ? { onPointerEnter, onPointerMove, onPointerLeave } : {},
    style,
    /** 0..1 position of the pointer, for a progress hairline. */
    fraction: style ? fraction : null,
  }
}
