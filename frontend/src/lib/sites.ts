import type { RoomState } from '@/lib/api'

/** Display names for site keys stored on each model (`users.site`). */
const SITE_LABELS: Record<string, string> = {
  flirt4free: 'Flirt4Free',
}

export function siteLabel(site: string | null | undefined): string {
  return (site && SITE_LABELS[site]) || site || 'Unknown site'
}

/** Public profile page for a model on its site. */
export function profileUrl(site: string, username: string): string {
  switch (site) {
    case 'flirt4free':
      return `https://www.flirt4free.com/?model=${encodeURIComponent(username)}`
    default:
      return '#'
  }
}

export function roomStateLabel(state: RoomState | null | undefined): string {
  switch (state) {
    case 'public':
      return 'Live (public)'
    case 'private':
      return 'In a private show'
    case 'not_found':
      return 'Not found'
    case 'offline':
      return 'Offline'
    default:
      return 'Not checked yet'
  }
}
