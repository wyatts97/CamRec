import { useQuery } from '@tanstack/react-query'
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts'
import {
  BarChart3,
  Clock,
  Video,
  HardDrive,
  Scissors,
  MessageCircle,
  Gift,
  Gem,
  Users,
} from 'lucide-react'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/selia/card'
import EmptyState from '@/components/EmptyState'
import { api } from '@/lib/api'
import QueryError from '@/components/QueryError'
import { formatBytes } from '@/lib/utils'



function StatCard({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: string | number
  sub?: string
}) {
  return (
    <Card>
      <CardBody className="flex items-center gap-4 py-5">
        <div className="flex items-center justify-center h-11 w-11 rounded-xl bg-primary-subtle shrink-0">
          <Icon className="h-5 w-5 text-primary-ink" />
        </div>
        <div className="min-w-0">
          <p className="text-2xl font-bold text-foreground leading-tight">{value}</p>
          <p className="text-xs text-muted-foreground">{label}</p>
          {sub && <p className="text-xs text-muted-foreground/70 mt-0.5">{sub}</p>}
        </div>
      </CardBody>
    </Card>
  )
}

function ChartTooltipStyle() {
  return {
    backgroundColor: 'var(--popover)',
    border: '1px solid var(--border)',
    borderRadius: '0.5rem',
    color: 'var(--popover-foreground)',
    fontSize: '0.8rem',
  }
}

export default function Stats() {
  const { data: overview, isLoading: overviewLoading, isError: overviewError, error: overviewErr, refetch: refetchOverview } = useQuery({
    queryKey: ['stats', 'overview'],
    queryFn: () => api.stats.overview(),
  })

  const { data: perDay = [] } = useQuery({
    queryKey: ['stats', 'perDay'],
    queryFn: () => api.stats.recordingsPerDay(30),
  })

  const { data: topStreamers = [] } = useQuery({
    queryKey: ['stats', 'topStreamers'],
    queryFn: () => api.stats.topStreamers(8),
  })

  const { data: storageByUser = [] } = useQuery({
    queryKey: ['stats', 'storageByUser'],
    queryFn: () => api.stats.storageByUser(8),
  })

  const { data: volume = [] } = useQuery({
    queryKey: ['stats', 'volume'],
    queryFn: () => api.stats.giftChatVolume(8),
  })

  const storageData = storageByUser.map((s) => ({
    username: `@${s.username}`,
    gb: +(s.bytes / 1024 ** 3).toFixed(2),
    bytes: s.bytes,
  }))

  const volumeData = volume.map((v) => ({
    username: `@${v.username}`,
    chat: v.chat_count,
    gifts: v.gift_count,
    diamonds: v.diamonds,
  }))

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-primary-subtle">
          <BarChart3 className="h-5 w-5 text-primary-ink" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-foreground tracking-tight">Analytics</h1>
          <p className="text-sm text-muted-foreground">Insights across your recordings and live activity</p>
        </div>
      </div>

      {overviewError ? (
        <QueryError error={overviewErr} what="analytics" onRetry={() => refetchOverview()} />
      ) : (
      <>
      {/* Headline stats */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        <StatCard icon={Clock} label="Total hours recorded" value={overviewLoading ? '—' : `${overview?.total_hours ?? 0}h`} />
        <StatCard icon={Video} label="Recordings" value={overviewLoading ? '—' : overview?.total_recordings ?? 0} />
        <StatCard icon={HardDrive} label="Storage used" value={overviewLoading ? '—' : formatBytes(overview?.total_storage ?? 0)} sub={overview ? `+${formatBytes(overview.clip_storage)} clips` : undefined} />
        <StatCard icon={Scissors} label="Clips" value={overviewLoading ? '—' : overview?.total_clips ?? 0} />
        <StatCard icon={MessageCircle} label="Chat messages" value={overviewLoading ? '—' : (overview?.total_chat_messages ?? 0).toLocaleString()} />
        <StatCard icon={Gift} label="Gifts received" value={overviewLoading ? '—' : (overview?.total_gifts ?? 0).toLocaleString()} />
        <StatCard icon={Gem} label="Diamonds" value={overviewLoading ? '—' : (overview?.total_diamonds ?? 0).toLocaleString()} />
        <StatCard icon={Users} label="Monitored users" value={overviewLoading ? '—' : `${overview?.monitored_users ?? 0}/${overview?.total_users ?? 0}`} />
      </div>

      {/* Recordings per day */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recordings per day (last 30 days)</CardTitle>
        </CardHeader>
        <CardBody>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={perDay} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                <defs>
                  <linearGradient id="recGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--primary)" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="var(--primary)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }}
                  tickFormatter={(d: string) => d.slice(5)}
                  minTickGap={24}
                />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} />
                <Tooltip contentStyle={ChartTooltipStyle()} />
                <Area type="monotone" dataKey="count" name="Recordings" stroke="var(--primary)" strokeWidth={2} fill="url(#recGradient)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </CardBody>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Top streamers */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Most-active streamers</CardTitle>
          </CardHeader>
          <CardBody>
            {topStreamers.length === 0 ? (
              <EmptyState icon={Users} title="No data yet" description="Record some streams to see your top streamers." />
            ) : (
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={topStreamers} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
                    <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} />
                    <YAxis type="category" dataKey="username" width={90} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} tickFormatter={(u: string) => `@${u}`} />
                    <Tooltip contentStyle={ChartTooltipStyle()} cursor={{ fill: 'var(--accent)' }} />
                    {/* One series, so one colour. Colouring each bar from a
                        cycled palette double-encoded bar length as hue while
                        the username was already on the axis -- the colour
                        carried no information. */}
                    <Bar dataKey="count" name="Recordings" fill="var(--primary)" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardBody>
        </Card>

        {/* Storage by user */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Storage by user</CardTitle>
          </CardHeader>
          <CardBody>
            {storageData.length === 0 ? (
              <EmptyState icon={HardDrive} title="No data yet" description="Storage usage will appear once you have recordings." />
            ) : (
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={storageData} margin={{ top: 4, right: 8, left: -8, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis dataKey="username" tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }} interval={0} angle={-20} textAnchor="end" height={50} />
                    <YAxis tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} unit="GB" />
                    <Tooltip
                      contentStyle={ChartTooltipStyle()}
                      cursor={{ fill: 'var(--accent)' }}
                      formatter={(_v: any, _n: any, p: any) => [formatBytes(p.payload.bytes), 'Storage']}
                    />
                    {/* One series, one colour -- see the top-streamers chart. */}
                    <Bar dataKey="gb" name="Storage" fill="var(--primary)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* Gift / chat volume per stream */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Chat & gift volume per stream</CardTitle>
        </CardHeader>
        <CardBody>
          {volumeData.length === 0 ? (
            <EmptyState icon={MessageCircle} title="No live events captured" description="Chat and gift activity from live recordings will appear here." />
          ) : (
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={volumeData} margin={{ top: 4, right: 8, left: -8, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="username" tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }} interval={0} angle={-20} textAnchor="end" height={50} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} />
                  <Tooltip contentStyle={ChartTooltipStyle()} cursor={{ fill: 'var(--accent)' }} />
                  {/* Two series, so identity is never colour-alone: the legend
                      is always present. These use the fixed --chart-* tokens
                      rather than --primary because the pair must stay
                      distinguishable under colour-vision deficiency whichever
                      accent the user picks. */}
                  <Legend
                    verticalAlign="top"
                    align="right"
                    height={28}
                    iconType="circle"
                    iconSize={8}
                    wrapperStyle={{ fontSize: '0.75rem', color: 'var(--muted-foreground)' }}
                  />
                  <Bar dataKey="chat" name="Chat messages" stackId="a" fill="var(--chart-1)" radius={[0, 0, 0, 0]} />
                  {/* 2px surface gap so the two stacked segments read as separate marks. */}
                  <Bar dataKey="gifts" name="Gifts" stackId="a" fill="var(--chart-2)" radius={[4, 4, 0, 0]} stroke="var(--card)" strokeWidth={2} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardBody>
      </Card>
      </>
      )}
    </div>
  )
}
