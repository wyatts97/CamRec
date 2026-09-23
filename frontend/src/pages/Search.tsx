import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Search as SearchIcon, FileText, MessageCircle, Gift, Clock, Play } from 'lucide-react'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/selia/card'
import { Input } from '@/components/selia/input'
import { Badge } from '@/components/selia/badge'
import EmptyState from '@/components/EmptyState'
import { api } from '@/lib/api'
import { formatDuration } from '@/lib/utils'

export default function GlobalSearch() {
  const navigate = useNavigate()
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['globalSearch', query],
    queryFn: () => api.search.global(query),
    enabled: query.trim().length >= 2,
  })

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setQuery(input.trim())
  }

  const jumpTo = (recordingId: number, seconds: number) => {
    navigate(`/watch/${recordingId}?t=${Math.floor(seconds)}`)
  }

  const transcripts = data?.transcripts ?? []
  const events = data?.events ?? []
  const hasResults = transcripts.length > 0 || events.length > 0

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-primary-subtle">
          <SearchIcon className="h-5 w-5 text-primary-ink" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-foreground tracking-tight">Library Search</h1>
          <p className="text-sm text-muted-foreground">Search transcripts and live chat across all recordings</p>
        </div>
      </div>

      <form onSubmit={submit} className="relative max-w-2xl">
        <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          autoFocus
          placeholder="Search words spoken or typed in chat…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="pl-10 h-11"
        />
      </form>

      {query.trim().length < 2 ? (
        <EmptyState
          icon={SearchIcon}
          title="Search your whole library"
          description="Find moments by transcript text or by what viewers said in chat. Type at least 2 characters and press Enter."
        />
      ) : isLoading ? (
        <div className="flex items-center justify-center py-16" role="status" aria-label="Searching">
          <svg className="h-6 w-6 animate-spin motion-reduce:animate-none text-primary-ink" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 12a9 9 0 1 1-6.219-8.56" />
          </svg>
        </div>
      ) : isError ? (
        <EmptyState icon={SearchIcon} title="Search failed" description={(error as Error)?.message || 'Try a different query.'} />
      ) : !hasResults ? (
        <EmptyState icon={SearchIcon} title="No matches" description={`Nothing found for “${query}”. Try another term.`} />
      ) : (
        <div className="space-y-6">
          {/* Transcript results */}
          {transcripts.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <FileText className="h-4 w-4 text-primary-ink" />
                  Transcripts
                  <Badge variant="secondary" size="sm">{data?.transcript_count}</Badge>
                </CardTitle>
              </CardHeader>
              <CardBody className="space-y-4">
                {transcripts.map((t) => (
                  <div key={t.recording_id} className="rounded-lg border border-border p-3">
                    <button
                      onClick={() => navigate(`/watch/${t.recording_id}`)}
                      className="text-sm font-medium text-foreground hover:text-primary-ink transition-colors"
                    >
                      @{t.username} · Recording #{t.recording_id}
                    </button>
                    <div className="mt-2 space-y-1.5">
                      {t.matches.map((m, i) => (
                        <button
                          key={i}
                          onClick={() => jumpTo(t.recording_id, m.offset_seconds)}
                          className="group flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-accent transition-colors"
                        >
                          <span className="inline-flex items-center gap-1 shrink-0 text-xs font-mono text-primary-ink">
                            <Clock className="h-3 w-3" />
                            {formatDuration(m.offset_seconds)}
                          </span>
                          <span className="text-sm text-muted-foreground group-hover:text-foreground line-clamp-2">
                            {m.snippet}
                          </span>
                          <Play className="h-3.5 w-3.5 ml-auto shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100" />
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </CardBody>
            </Card>
          )}

          {/* Chat / gift results */}
          {events.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <MessageCircle className="h-4 w-4 text-primary-ink" />
                  Chat & gifts
                  <Badge variant="secondary" size="sm">{data?.event_count}</Badge>
                </CardTitle>
              </CardHeader>
              <CardBody className="divide-y divide-border">
                {events.map((ev) => (
                  <button
                    key={ev.id}
                    onClick={() => jumpTo(ev.recording_id, ev.offset_seconds)}
                    className="group flex w-full items-start gap-3 py-2.5 text-left hover:bg-accent -mx-2 px-2 rounded-md transition-colors"
                  >
                    <span className="inline-flex items-center gap-1 shrink-0 text-xs font-mono text-primary-ink pt-0.5">
                      <Clock className="h-3 w-3" />
                      {formatDuration(ev.offset_seconds)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs text-muted-foreground">
                        @{ev.username} · {ev.user_nickname}
                      </p>
                      <p className="text-sm text-foreground flex items-center gap-1.5">
                        {ev.event_type === 'gift' ? (
                          <>
                            <Gift className="h-3.5 w-3.5 text-warning shrink-0" />
                            <span>Sent {ev.gift_name}</span>
                          </>
                        ) : (
                          <span className="line-clamp-2">{ev.content}</span>
                        )}
                      </p>
                    </div>
                    <Play className="h-3.5 w-3.5 shrink-0 self-center text-muted-foreground opacity-0 group-hover:opacity-100" />
                  </button>
                ))}
              </CardBody>
            </Card>
          )}
        </div>
      )}
    </div>
  )
}
