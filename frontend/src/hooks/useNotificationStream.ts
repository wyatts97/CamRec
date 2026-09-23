import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, notifyUnauthorized, type AppNotification } from '@/lib/api'

/** Give up reconnecting after this many consecutive failures. */
const MAX_FAILURES = 5

type NotificationCache = { notifications: AppNotification[]; unread: number }

/**
 * Subscribes to the notification SSE stream.
 *
 * Mount this exactly once, from Layout: the sidebar renders twice (desktop and
 * the mobile drawer), and owning the EventSource in a component that renders
 * twice opened two connections and fired every desktop notification twice.
 */
export function useNotificationStream() {
  const queryClient = useQueryClient()

  useEffect(() => {
    let es: EventSource | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let failures = 0
    let cancelled = false

    const connect = () => {
      if (cancelled) return
      es = new EventSource(api.notifications.streamUrl())

      es.onopen = () => {
        failures = 0
      }

      es.onmessage = (e) => {
        let notif: AppNotification | null = null
        try {
          notif = JSON.parse(e.data)
        } catch {
          return
        }
        if (!notif || !notif.id) return
        const incoming = notif

        queryClient.setQueryData(
          ['notifications'],
          (old: NotificationCache | undefined) => {
            const list = old?.notifications ?? []
            if (list.some((n) => n.id === incoming.id)) return old
            return {
              notifications: [incoming, ...list].slice(0, 50),
              unread: (old?.unread ?? 0) + 1,
            }
          }
        )

        // Recording lifecycle events also mean the recording lists are stale.
        // Refreshing here lets the periodic polls elsewhere stay slow.
        if (incoming.type === 'user_live' || incoming.type.startsWith('recording_')) {
          queryClient.invalidateQueries({ queryKey: ['activeRecordings'] })
          queryClient.invalidateQueries({ queryKey: ['recordings'] })
          queryClient.invalidateQueries({ queryKey: ['recording'] })
          queryClient.invalidateQueries({ queryKey: ['users'] })
        } else if (incoming.type === 'clip_ready') {
          queryClient.invalidateQueries({ queryKey: ['clips'] })
        }

        if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
          try {
            new Notification(incoming.title, {
              body: incoming.message,
              tag: `camsuite-${incoming.id}`,
            })
          } catch {
            /* ignore */
          }
        }
      }

      es.onerror = () => {
        // EventSource can see neither the status code nor the body, so an
        // expired session looks exactly like a network blip -- and the built-in
        // reconnect then hammers a 401 endpoint forever. Take reconnection over
        // ourselves: close, back off, and after a few failures ask the server
        // whether we are still logged in.
        es?.close()
        es = null
        failures += 1

        if (failures >= MAX_FAILURES) {
          api.auth
            .status()
            .then((s) => {
              if (!cancelled && !s.authenticated) notifyUnauthorized()
            })
            .catch(() => {})
          return
        }

        retryTimer = setTimeout(connect, Math.min(30_000, 1_000 * 2 ** failures))
      }
    }

    connect()

    return () => {
      cancelled = true
      if (retryTimer) clearTimeout(retryTimer)
      es?.close()
    }
  }, [queryClient])
}
