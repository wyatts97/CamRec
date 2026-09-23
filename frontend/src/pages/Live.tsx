import { useQuery } from '@tanstack/react-query'
import { Tv } from 'lucide-react'
import { api } from '@/lib/api'
import LiveProfileCard from '@/components/LiveProfileCard'
import EmptyState from '@/components/EmptyState'
import QueryError from '@/components/QueryError'
import { StaggerContainer, StaggerItem } from '@/components/motion'

export default function Live() {
  // Elapsed-time badges on the cards come from this poll; the notification
  // stream refreshes it immediately when a recording starts or ends.
  const { data: activeRecordings = [], isLoading, isError, error, refetch } = useQuery({
    queryKey: ['activeRecordings'],
    queryFn: () => api.recordings.getActive(),
    refetchInterval: 5000,
  })

  const { data: users = [] } = useQuery({
    queryKey: ['users'],
    queryFn: () => api.users.list(),
  })
  const displayNames = new Map(users.map((u) => [u.id, u.display_name]))

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-foreground">Live streams</h1>
        <p className="text-muted mt-1">
          {activeRecordings.length === 0
            ? 'Streams being recorded show up here.'
            : `${activeRecordings.length} ${activeRecordings.length === 1 ? 'stream' : 'streams'} recording now. Watch any of them right here.`}
        </p>
      </div>

      {isError ? (
        <QueryError error={error} what="active recordings" onRetry={() => refetch()} />
      ) : isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-[420px] rounded-xl bg-secondary animate-pulse motion-reduce:animate-none" />
          ))}
        </div>
      ) : activeRecordings.length === 0 ? (
        <EmptyState
          icon={Tv}
          title="Nothing live right now"
          description="When someone on your watchlist goes live and recording starts, their stream appears here."
        />
      ) : (
        <StaggerContainer className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {activeRecordings.map((rec) => (
            <StaggerItem key={rec.id}>
              <LiveProfileCard
                userId={rec.user_id}
                username={rec.username}
                displayName={displayNames.get(rec.user_id)}
                recording={rec}
                playable
              />
            </StaggerItem>
          ))}
        </StaggerContainer>
      )}
    </div>
  )
}
