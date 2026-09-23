import { Fragment, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ArrowRight, BellRing, Film, Radio, Scissors, Users, Video } from 'lucide-react'
import { Card, CardBody, CardHeader, CardHeaderAction, CardTitle } from '@/components/selia/card'
import { Button } from '@/components/selia/button'
import { IconBox } from '@/components/selia/icon-box'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/selia/avatar'
import { Stack } from '@/components/selia/stack'
import { Separator } from '@/components/selia/separator'
import {
  Item,
  ItemAction,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemMeta,
  ItemTitle,
} from '@/components/selia/item'
import LiveProfileCard from '@/components/LiveProfileCard'
import QueryError from '@/components/QueryError'
import { RecordingVideoCard } from '@/components/ui/recording-video-card'
import { ClipCard } from '@/components/ui/clip-card'
import { api, type ActiveRecording, type AppNotification, type User } from '@/lib/api'
import { cn, formatBytes } from '@/lib/utils'
import { notificationIcon, notificationTarget, timeAgo } from '@/lib/notifications'
import toast from 'react-hot-toast'

// Four fills one desktop row exactly (grid-cols-4) and a 2x2 grid on tablets.
const RAIL_SIZE = 4
const ACTIVITY_SIZE = 12

export default function Dashboard() {
  const queryClient = useQueryClient()

  const { data: users = [], isLoading: usersLoading, isError, error, refetch } = useQuery({
    queryKey: ['users'],
    queryFn: () => api.users.list(),
    refetchInterval: 30000,
  })

  // Elapsed-time badges on the live cards come from this poll.
  const { data: activeRecordings = [] } = useQuery({
    queryKey: ['activeRecordings'],
    queryFn: () => api.recordings.getActive(),
    refetchInterval: 5000,
  })

  const { data: overview } = useQuery({
    queryKey: ['stats', 'overview'],
    queryFn: () => api.stats.overview(),
    refetchInterval: 60000,
  })

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.settings.health(),
    refetchInterval: 60000,
  })

  const startRecording = useMutation({
    mutationFn: (username: string) => api.recordings.start({ username }),
    onSuccess: (_rec, username) => {
      queryClient.invalidateQueries({ queryKey: ['activeRecordings'] })
      queryClient.invalidateQueries({ queryKey: ['recordings'] })
      toast.success(`Recording @${username}`)
    },
    onError: (err: Error) => toast.error(err.message),
  })

  // Repair a broken avatar once per user per visit.
  const repairedAvatars = useRef<Set<number>>(new Set())
  const repairAvatar = (id: number) => {
    if (repairedAvatars.current.has(id)) return
    repairedAvatars.current.add(id)
    api.users.refresh(id, true).catch(() => {})
  }

  if (isError) {
    return <QueryError error={error} what="your dashboard" onRetry={() => refetch()} />
  }

  const monitored = users.filter((u) => u.is_monitoring).length

  return (
    <div className="space-y-10">
      {health?.country_blacklisted && (
        <Card className="ring-warning/40 bg-warning/5">
          <CardBody className="flex items-start gap-3">
            <IconBox variant="warning-subtle" size="sm">
              <AlertCircle />
            </IconBox>
            <div>
              <p className="font-medium text-foreground">Region restricted</p>
              <p className="text-sm text-muted">
                TikTok access is restricted in your region. Configure cookies or a proxy in{' '}
                <Link to="/settings" className="underline">Settings</Link>.
              </p>
            </div>
          </CardBody>
        </Card>
      )}

      <LiveNow
        users={users}
        activeRecordings={activeRecordings}
        loading={usersLoading}
        onRecord={(username) => startRecording.mutate(username)}
        pendingUsername={startRecording.isPending ? startRecording.variables : undefined}
        onAvatarError={repairAvatar}
      />

      <section aria-label="Library at a glance" className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        <StatCard
          to="/watchlist"
          icon={Users}
          label="Watchlist"
          value={users.length}
          detail={`${monitored} monitored`}
        />
        <StatCard
          to="/recordings"
          icon={Film}
          label="Recordings"
          value={overview?.total_recordings}
          detail={overview ? `${overview.total_hours} hours saved` : undefined}
        />
        <StatCard
          to="/clips"
          icon={Scissors}
          label="Clips"
          value={overview?.total_clips}
          detail={overview ? formatBytes(overview.clip_storage) : undefined}
        />
        <StatCard
          to="/live"
          icon={Video}
          label="Recording now"
          value={activeRecordings.length}
          detail={activeRecordings.length === 1 ? '1 stream' : `${activeRecordings.length} streams`}
        />
      </section>

      <LatestRecordings />
      <RecentClips />
      <RecentActivity />
    </div>
  )
}

/* ------------------------------------------------------------------------ */

function SectionHeader({ title, to, linkLabel }: { title: string; to?: string; linkLabel?: string }) {
  return (
    <div className="flex items-end justify-between gap-4 mb-4">
      <h2 className="text-xl font-semibold tracking-tight text-foreground">{title}</h2>
      {to && (
        <Link
          to={to}
          className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground transition-colors"
        >
          {linkLabel ?? 'View all'}
          <ArrowRight className="size-3.5" aria-hidden="true" />
        </Link>
      )}
    </div>
  )
}

/** Horizontal snap-scroll rail on small screens, a grid from `sm` up. */
function Rail({ children, columns = 3 }: { children: React.ReactNode; columns?: 3 | 4 }) {
  return (
    <div
      className={cn(
        // scroll-px keeps snapped cards clear of the screen edge on phones.
        '-mx-4 px-4 scroll-px-4 sm:mx-0 sm:px-0 flex sm:grid gap-4 sm:grid-cols-2',
        columns === 4 ? 'lg:grid-cols-4' : 'lg:grid-cols-3',
        'overflow-x-auto sm:overflow-visible snap-x snap-mandatory pb-2 sm:pb-0',
        '*:shrink-0 *:w-[80%] sm:*:w-auto *:snap-start',
      )}
    >
      {children}
    </div>
  )
}

function LiveNow({
  users,
  activeRecordings,
  loading,
  onRecord,
  pendingUsername,
  onAvatarError,
}: {
  users: User[]
  activeRecordings: ActiveRecording[]
  loading: boolean
  onRecord: (username: string) => void
  pendingUsername?: string
  onAvatarError: (id: number) => void
}) {
  const recordingByUser = new Map(activeRecordings.map((r) => [r.user_id, r]))
  // Anyone being recorded is live, even if the last watchlist check lags.
  const live = users
    .filter((u) => u.is_live || recordingByUser.has(u.id))
    .sort((a, b) => Number(recordingByUser.has(b.id)) - Number(recordingByUser.has(a.id)))

  return (
    <section aria-labelledby="live-now-title">
      <div className="flex items-end justify-between gap-4 mb-4">
        <div>
          <h1 id="live-now-title" className="text-3xl font-bold tracking-tight text-foreground">
            Live now
          </h1>
          <p className="text-muted mt-1">
            {loading
              ? 'Checking who is live…'
              : live.length === 0
                ? 'Nobody you watch is streaming right now.'
                : `${live.length} of your creators ${live.length === 1 ? 'is' : 'are'} streaming.`}
          </p>
        </div>
        {live.length > 0 && (
          <Link
            to="/live"
            className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground transition-colors"
          >
            All streams
            <ArrowRight className="size-3.5" aria-hidden="true" />
          </Link>
        )}
      </div>

      {loading ? (
        <Rail>
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-[420px] rounded-xl bg-secondary animate-pulse motion-reduce:animate-none" />
          ))}
        </Rail>
      ) : live.length === 0 ? (
        <div className="h-40 rounded-xl border border-dashed border-border flex items-center justify-center">
          <Radio className="size-5 text-dimmed" aria-hidden="true" />
        </div>
      ) : (
        <Rail>
          {live.map((user) => (
            <LiveProfileCard
              key={user.id}
              userId={user.id}
              username={user.username}
              displayName={user.display_name}
              recording={recordingByUser.get(user.id)}
              onRecord={() => onRecord(user.username)}
              recordPending={pendingUsername === user.username}
              onAvatarError={() => onAvatarError(user.id)}
            />
          ))}
        </Rail>
      )}
    </section>
  )
}

function StatCard({
  to,
  icon: Icon,
  label,
  value,
  detail,
}: {
  to: string
  icon: typeof Users
  label: string
  value: number | undefined
  detail?: string
}) {
  return (
    <Link
      to={to}
      className="group rounded-xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
    >
      <Card className="h-full transition-shadow group-hover:shadow-md">
        <CardBody className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-muted">{label}</span>
            <IconBox variant="secondary-subtle" size="sm">
              <Icon />
            </IconBox>
          </div>
          <div>
            {value === undefined ? (
              <div className="h-8 w-16 rounded bg-accent animate-pulse motion-reduce:animate-none" />
            ) : (
              <p className="text-3xl font-semibold tabular-nums text-foreground">{value.toLocaleString()}</p>
            )}
            <p className="text-xs text-dimmed mt-1 h-4">{detail}</p>
          </div>
        </CardBody>
      </Card>
    </Link>
  )
}

function LatestRecordings() {
  const navigate = useNavigate()
  const { data } = useQuery({
    queryKey: ['recordings', 'dashboard-latest'],
    queryFn: () => api.recordings.list(1, RAIL_SIZE, 'completed,stopped'),
  })
  const recordings = data?.recordings ?? []
  if (data && recordings.length === 0) return null

  return (
    <section aria-label="Latest recordings">
      <SectionHeader title="Latest recordings" to="/watch" />
      <Rail columns={4}>
        {recordings.map((rec) => (
          <RecordingVideoCard key={rec.id} recording={rec} onClick={() => navigate(`/watch/${rec.id}`)} />
        ))}
      </Rail>
    </section>
  )
}

function RecentClips() {
  const navigate = useNavigate()
  const { data } = useQuery({
    queryKey: ['clips', 'dashboard-recent'],
    queryFn: () => api.clips.list(1, RAIL_SIZE, 'date', 'desc'),
  })
  const clips = data?.clips ?? []
  if (data && clips.length === 0) return null

  return (
    <section aria-label="Recent clips">
      <SectionHeader title="Recent clips" to="/clips" />
      <Rail columns={4}>
        {clips.map((clip) => (
          <ClipCard key={clip.id} clip={clip} onClick={() => navigate(`/clips/${clip.id}`)} />
        ))}
      </Rail>
    </section>
  )
}

type NotificationCache = { notifications: AppNotification[]; unread: number }

function RecentActivity() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [permission, setPermission] = useState<NotificationPermission>(
    typeof Notification !== 'undefined' ? Notification.permission : 'denied',
  )

  // Same cache key the SSE stream prepends new notifications into.
  const { data } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => api.notifications.list(50),
    refetchInterval: 60000,
  })
  const items = (data?.notifications ?? []).slice(0, ACTIVITY_SIZE)
  const unread = data?.unread ?? 0

  // Seeing the feed counts as reading it.
  useEffect(() => {
    if (unread === 0) return
    const t = setTimeout(() => {
      api.notifications
        .markAllRead()
        .then(() =>
          queryClient.setQueryData(['notifications'], (old: NotificationCache | undefined) =>
            old ? { ...old, unread: 0 } : old,
          ),
        )
        .catch(() => {})
    }, 1500)
    return () => clearTimeout(t)
  }, [unread, queryClient])

  const enableDesktop = async () => {
    if (typeof Notification === 'undefined') return
    setPermission(await Notification.requestPermission())
  }

  return (
    <section aria-label="Recent activity">
      <Card>
        <CardHeader>
          <CardTitle>Recent activity</CardTitle>
          {permission === 'default' && (
            <CardHeaderAction>
              <Button variant="plain" size="sm" onClick={enableDesktop}>
                <BellRing />
                Desktop alerts
              </Button>
            </CardHeaderAction>
          )}
        </CardHeader>
        <CardBody>
          {items.length === 0 ? (
            <p className="text-sm text-muted text-center py-6">
              Streams going live, finished recordings and new clips will show up here.
            </p>
          ) : (
            // Selia's Stack-of-Items pattern: CardBody bleeds the stack to the
            // card edges and pads each item.
            <Stack>
              {items.map((n, i) => (
                <Fragment key={n.id}>
                  {i > 0 && <Separator />}
                  <ActivityItem
                    notification={n}
                    onOpen={(to) => navigate(to)}
                  />
                </Fragment>
              ))}
            </Stack>
          )}
        </CardBody>
      </Card>
    </section>
  )
}

function ActivityItem({
  notification: n,
  onOpen,
}: {
  notification: AppNotification
  onOpen: (to: string) => void
}) {
  const { Icon, variant } = notificationIcon(n.type)
  const target = notificationTarget(n)
  const userId: number | undefined = n.data?.user_id

  return (
    <Item variant="plain">
      <ItemMedia>
        {userId ? (
          <Avatar size="md">
            <AvatarImage src={api.users.getAvatarUrl(userId)} alt="" />
            <AvatarFallback>
              <Icon className="size-4.5" />
            </AvatarFallback>
          </Avatar>
        ) : (
          <IconBox variant={variant}>
            <Icon />
          </IconBox>
        )}
      </ItemMedia>
      <ItemContent>
        <ItemTitle>{n.title}</ItemTitle>
        <ItemMeta className={n.message ? 'mb-1.5' : undefined}>
          <time dateTime={n.created_at} title={new Date(n.created_at).toLocaleString()}>
            {timeAgo(n.created_at)}
          </time>
        </ItemMeta>
        {n.message && <ItemDescription className="text-sm">{n.message}</ItemDescription>}
      </ItemContent>
      {target && (
        <ItemAction>
          <Button variant="outline" size="xs" onClick={() => onOpen(target)}>
            Open
          </Button>
        </ItemAction>
      )}
    </Item>
  )
}
