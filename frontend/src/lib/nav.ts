import {
  LayoutDashboard,
  Users,
  Video,
  Tv,
  Radio,
  Scissors,
  Database,
  Settings,
} from 'lucide-react'

/** Sidebar section headings, in display order. */
export const NAV_GROUPS = ['Overview', 'Watch', 'Library', 'System'] as const

export type NavGroup = (typeof NAV_GROUPS)[number]

/**
 * The app's navigation destinations.
 *
 * Single source of truth for the sidebar and the command palette. The
 * sidebar groups these by `group`; Settings has no group and is pinned to the
 * sidebar footer.
 */
export const NAV_ITEMS: ReadonlyArray<{
  to: string
  icon: typeof LayoutDashboard
  label: string
  group: NavGroup | null
}> = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard', group: 'Overview' },
  { to: '/live', icon: Radio, label: 'Live', group: 'Watch' },
  { to: '/watch', icon: Tv, label: 'Watch', group: 'Watch' },
  { to: '/clips', icon: Scissors, label: 'Clips', group: 'Watch' },
  { to: '/watchlist', icon: Users, label: 'Watchlist', group: 'Library' },
  { to: '/recordings', icon: Video, label: 'Recordings', group: 'Library' },
  { to: '/storage', icon: Database, label: 'Storage', group: 'System' },
  { to: '/settings', icon: Settings, label: 'Settings', group: null },
]

export function isNavActive(pathname: string, to: string): boolean {
  return pathname === to || (to !== '/' && pathname.startsWith(to + '/'))
}
