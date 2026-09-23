import {
  LayoutDashboard,
  Users,
  Video,
  Tv,
  Radio,
  Scissors,
  BarChart3,
  Search,
  Database,
  Settings,
} from 'lucide-react'

/** Sidebar section headings, in display order. */
export const NAV_GROUPS = ['Overview', 'Watch', 'Library', 'Insights'] as const

export type NavGroup = (typeof NAV_GROUPS)[number]

/**
 * The app's navigation destinations.
 *
 * Single source of truth: the sidebar and the command palette kept separate
 * copies, and the palette's had drifted to five entries -- Live, Clips, Stats,
 * Search and Storage were unreachable from it. The sidebar groups these by
 * `group`; Settings has no group and is pinned to the sidebar footer.
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
  { to: '/search', icon: Search, label: 'Search', group: 'Library' },
  { to: '/stats', icon: BarChart3, label: 'Stats', group: 'Insights' },
  { to: '/storage', icon: Database, label: 'Storage', group: 'Insights' },
  { to: '/settings', icon: Settings, label: 'Settings', group: null },
]

export function isNavActive(pathname: string, to: string): boolean {
  return pathname === to || (to !== '/' && pathname.startsWith(to + '/'))
}
