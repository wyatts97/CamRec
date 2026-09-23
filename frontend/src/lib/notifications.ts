import {
  Bell,
  Radio,
  Video,
  Scissors,
  AlertCircle,
  CheckCircle2,
  Lock,
  ShieldAlert,
} from 'lucide-react'
import type { AppNotification } from '@/lib/api'

type IconBoxVariant =
  | 'danger-subtle'
  | 'success-subtle'
  | 'secondary-subtle'
  | 'primary-subtle'
  | 'warning-subtle'

/** Icon and IconBox tone for a notification type. */
export function notificationIcon(type: string): { Icon: typeof Bell; variant: IconBoxVariant } {
  switch (type) {
    case 'user_live':
      return { Icon: Radio, variant: 'danger-subtle' }
    case 'recording_completed':
      return { Icon: CheckCircle2, variant: 'success-subtle' }
    case 'recording_failed':
      return { Icon: AlertCircle, variant: 'danger-subtle' }
    case 'recording_stopped':
      return { Icon: Video, variant: 'secondary-subtle' }
    case 'clip_ready':
      return { Icon: Scissors, variant: 'primary-subtle' }
    case 'private_live':
      return { Icon: Lock, variant: 'warning-subtle' }
    case 'circuit_breaker_tripped':
    case 'mass_live_anomaly':
      return { Icon: ShieldAlert, variant: 'warning-subtle' }
    default:
      return { Icon: Bell, variant: 'secondary-subtle' }
  }
}

export function timeAgo(iso: string): string {
  const diff = Math.max(0, Date.now() - new Date(iso).getTime())
  const s = Math.floor(diff / 1000)
  if (s < 60) return 'just now'
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} minute${m === 1 ? '' : 's'} ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} hour${h === 1 ? '' : 's'} ago`
  const d = Math.floor(h / 24)
  return `${d} day${d === 1 ? '' : 's'} ago`
}

/** Where opening a notification should take the user, or null if nowhere. */
export function notificationTarget(n: AppNotification): string | null {
  const d = n.data || {}
  if (d.clip_id) return `/clips/${d.clip_id}`
  if (n.type === 'user_live') return d.recording_id ? `/live/${d.recording_id}` : '/live'
  if (d.recording_id && n.type === 'recording_completed') return `/watch/${d.recording_id}`
  if (d.recording_id) return '/recordings'
  if (n.type === 'private_live' || n.type === 'circuit_breaker_tripped') return '/watchlist'
  return null
}
