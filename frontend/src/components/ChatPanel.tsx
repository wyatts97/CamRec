import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { MessageCircle, Search, Loader2 } from 'lucide-react'
import { Input } from 'components/selia/input'
import { api } from '@/lib/api'
import type { Recording, LiveEvent } from '@/lib/api'

function formatOffset(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

const EVENT_PAGE_SIZE = 500

interface ChatPanelProps {
  recording: Recording
  chatSearch: string
  onChatSearchChange: (value: string) => void
  onSeek?: (seconds: number) => void
  /** Render as a standalone panel (desktop) vs inline (mobile) */
  variant?: 'panel' | 'inline'
}

export default function ChatPanel({
  recording,
  chatSearch,
  onChatSearchChange,
  onSeek,
  variant = 'inline',
}: ChatPanelProps) {
  const [tabFilter, setTabFilter] = useState<'all' | 'chat' | 'gifts'>('all')

  // Accumulated locally so each poll only has to carry what is new. Fetching
  // the full window every 3s was the single most expensive thing in the app:
  // on a busy stream it re-downloaded megabytes a minute, per viewer.
  const [events, setEvents] = useState<LiveEvent[]>([])
  const afterIdRef = useRef<number | null>(null)

  // The buffer belongs to one (recording, filter) pair; changing either means
  // starting over rather than appending onto unrelated rows.
  useEffect(() => {
    setEvents([])
    afterIdRef.current = null
  }, [recording.id, tabFilter])

  const { isLoading } = useQuery({
    queryKey: ['live-events', recording.id, tabFilter],
    queryFn: async () => {
      const after = afterIdRef.current
      const res = await api.recordings.getEvents(
        recording.id,
        1,
        EVENT_PAGE_SIZE,
        tabFilter === 'all' ? undefined : tabFilter,
        undefined,
        after ?? undefined,
      )
      if (after === null) {
        setEvents(res.events)
      } else if (res.events.length > 0) {
        setEvents((prev) => [...prev, ...res.events])
      }
      // Advance the high-water mark. An empty first page leaves this at 0,
      // which correctly asks for "everything" on the next poll.
      afterIdRef.current = res.events.reduce((m, e) => Math.max(m, e.id), after ?? 0)
      return res
    },
    refetchInterval: recording.status === 'recording' ? 3000 : false,
  })

  // Memoised: this component polls every 3 seconds, and the filter previously
  // re-ran over up to 500 events on every render.
  const filteredEvents = useMemo(() => {
    if (!chatSearch) return events
    const q = chatSearch.toLowerCase()
    return events.filter((ev: LiveEvent) =>
      ev.user_nickname.toLowerCase().includes(q) ||
      ev.content?.toLowerCase().includes(q) ||
      ev.gift_name?.toLowerCase().includes(q)
    )
  }, [events, chatSearch])

  const scrollRef = useRef<HTMLDivElement>(null)
  const virtualizer = useVirtualizer({
    count: filteredEvents.length,
    getScrollElement: () => scrollRef.current,
    // Rows are one line most of the time; measureElement corrects the rest.
    estimateSize: () => 22,
    overscan: 12,
  })

  const content = (
    <>
      {/* Tab filter */}
      <div className="flex gap-1 border-b border-border pb-2">
        {(['all', 'chat', 'gifts'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setTabFilter(tab)}
            className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
              tabFilter === tab
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground hover:bg-accent'
            }`}
          >
            {tab === 'all' ? 'All' : tab === 'chat' ? 'Chat' : 'Gifts'}
          </button>
        ))}
      </div>

      {/* Search */}
      {events.length > 0 && (
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            placeholder="Search chat & gifts…"
            value={chatSearch}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChatSearchChange(e.target.value)}
            className="pl-8 h-8 text-sm"
          />
        </div>
      )}

      {/* Loading state */}
      {isLoading && (
        <div className="flex items-center gap-2 py-6 justify-center">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Loading events…</p>
        </div>
      )}

      {/* Empty states */}
      {!isLoading && events.length === 0 && recording.status === 'recording' && (
        <div className="flex flex-col items-center justify-center py-8 gap-3">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Waiting for chat events…</p>
        </div>
      )}

      {!isLoading && events.length === 0 && recording.status !== 'recording' && (
        <div className="flex flex-col items-center justify-center py-8 gap-3">
          <MessageCircle className="h-8 w-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No chat or gift events captured</p>
        </div>
      )}

      {/* Events list -- virtualised: a busy stream returns 500 events and
          rendering every one of them made the 3s poll janky. */}
      {filteredEvents.length > 0 && (
        <div ref={scrollRef} className="font-mono text-xs overflow-y-auto max-h-[60vh]">
          <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const ev = filteredEvents[virtualRow.index]
            return (
            <div
              key={ev.id}
              ref={virtualizer.measureElement}
              data-index={virtualRow.index}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
            <p key={ev.id} className={`leading-relaxed ${ev.event_type === 'gift' ? 'text-warning' : ''}`}>
              {onSeek ? (
                <button
                  onClick={() => onSeek(ev.offset_seconds)}
                  className="text-primary-ink hover:underline cursor-pointer"
                  title={`Jump to ${formatOffset(ev.offset_seconds)}`}
                >
                  [{formatOffset(ev.offset_seconds)}]
                </button>
              ) : (
                // Live streams can't seek, so the timestamp must not look clickable.
                <span className="text-muted-foreground">[{formatOffset(ev.offset_seconds)}]</span>
              )}
              {' '}
              <span className="font-semibold text-foreground">{ev.user_nickname}</span>
              {ev.event_type === 'chat' ? (
                <>: <span>{ev.content}</span></>
              ) : (
                <>
                  {' '}sent{' '}
                  <span className="font-semibold">{ev.gift_name}</span>
                  {ev.gift_repeat_count && ev.gift_repeat_count > 1 ? (
                    <span> (x{ev.gift_repeat_count})</span>
                  ) : null}
                  {ev.gift_diamond_count ? (
                    <span> 💎{ev.gift_diamond_count}</span>
                  ) : null}
                </>
              )}
            </p>
            </div>
            )
          })}
          </div>
        </div>
      )}
    </>
  )

  if (variant === 'panel') {
    return (
      <div className="hidden lg:flex w-80 shrink-0 flex-col border border-border rounded-xl overflow-hidden bg-card self-start max-h-[calc(100vh-6rem)]">
        <div className="px-4 py-3 border-b border-border bg-background flex items-center gap-2">
          <MessageCircle className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">Chat & Gifts</span>
          {events.length > 0 && (
            <span className="ml-auto h-1.5 w-1.5 rounded-full bg-success" />
          )}
        </div>
        <div className="flex-1 p-3 space-y-3 overflow-y-auto min-h-0">
          {content}
        </div>
      </div>
    )
  }

  // Inline variant — just the content
  return <div className="p-4 space-y-3">{content}</div>
}
