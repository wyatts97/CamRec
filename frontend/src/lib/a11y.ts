import type { KeyboardEvent } from 'react'

/**
 * Props that make a non-interactive container behave like a button.
 *
 * Several containers (dashboard stat cards, activity rows, live stream cards,
 * watchlist table rows) are navigable but were plain divs with only an
 * onClick: unreachable by keyboard and announced as nothing by screen readers.
 * Spread this onto them rather than re-deriving the handler each time.
 *
 * Prefer a real <button> or <a> when the element is not already a card/row --
 * this is for the cases where the semantics have to be layered on.
 */
export function clickable(onActivate: () => void, label?: string) {
  return {
    role: 'button',
    tabIndex: 0,
    'aria-label': label,
    onClick: onActivate,
    onKeyDown: (e: KeyboardEvent) => {
      // Enter and Space are what a real button responds to.
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        onActivate()
      }
    },
  } as const
}

/**
 * Arrow-key navigation for a manually-built tab strip.
 *
 * The player pages build their tab strips out of plain buttons and render the
 * panels as siblings rather than children, so they can't drop in the selia
 * Tabs primitive without restructuring. This gives them the same keyboard
 * contract: Left/Right move between tabs, Home/End jump to the ends.
 */
export function tabListKeyDown<T extends string>(
  tabs: readonly T[],
  active: T,
  onChange: (next: T) => void
) {
  return (e: KeyboardEvent) => {
    const i = tabs.indexOf(active)
    if (i === -1) return
    let next: number | null = null
    if (e.key === 'ArrowRight') next = (i + 1) % tabs.length
    else if (e.key === 'ArrowLeft') next = (i - 1 + tabs.length) % tabs.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = tabs.length - 1
    if (next === null) return
    e.preventDefault()
    onChange(tabs[next])
    // Move focus with the selection, as the tab pattern requires.
    const strip = e.currentTarget as HTMLElement
    strip.querySelectorAll<HTMLElement>('[role="tab"]')[next]?.focus()
  }
}

/** Props for one tab button in a strip built with {@link tabListKeyDown}. */
export function tabProps(id: string, isActive: boolean) {
  return {
    role: 'tab',
    id: `tab-${id}`,
    'aria-selected': isActive,
    'aria-controls': `tabpanel-${id}`,
    // Only the active tab is in the tab order; arrows move within the strip.
    tabIndex: isActive ? 0 : -1,
  } as const
}

/** Props for the panel belonging to a tab. */
export function tabPanelProps(id: string) {
  return {
    role: 'tabpanel',
    id: `tabpanel-${id}`,
    'aria-labelledby': `tab-${id}`,
    tabIndex: 0,
  } as const
}
