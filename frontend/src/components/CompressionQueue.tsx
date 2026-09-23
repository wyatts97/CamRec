import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Minimize2, Settings as SettingsIcon } from 'lucide-react'
import { Badge } from '@/components/selia/badge'
import { Button } from '@/components/selia/button'
import { Progress, ProgressLabel, ProgressValue } from '@/components/selia/progress'
import { api } from '@/lib/api'
import { formatBytes, formatDuration } from '@/lib/utils'
import toast from 'react-hot-toast'

/** "1h 5m", "12m", "40s" for rough estimates. */
function formatEta(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s}s`
  const m = Math.round(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

const QUEUE_PREVIEW = 8

/** Live view of the AV1 compression worker: the running job and what's waiting. */
export default function CompressionQueue() {
  const queryClient = useQueryClient()
  const { data: status, isLoading } = useQuery({
    queryKey: ['compressionStatus'],
    queryFn: () => api.settings.compressionStatus(),
    refetchInterval: (q) => (q.state.data?.current || q.state.data?.queue_length ? 2000 : 15000),
  })

  // When a job finishes, sizes on the rest of the page have changed.
  const lastJob = useRef<number | null>(null)
  const currentId = status?.current?.recording_id ?? null
  useEffect(() => {
    if (lastJob.current !== null && lastJob.current !== currentId) {
      for (const key of ['storageStats', 'storageByUser', 'largestRecordings', 'statsOverview', 'recordings']) {
        queryClient.invalidateQueries({ queryKey: [key] })
      }
    }
    lastJob.current = currentId
  }, [currentId, queryClient])

  const compressExisting = useMutation({
    mutationFn: () => api.settings.compressExisting(),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['compressionStatus'] })
      toast.success(res.queued ? `Queued ${res.queued} recording(s)` : 'Everything is already compressed')
    },
    onError: (e: Error) => toast.error(e.message),
  })

  if (isLoading || !status) return null

  const job = status.current
  const pct = job ? Math.round(job.progress * 100) : 0
  const state = !status.available
    ? { label: 'Unavailable', variant: 'warning' as const }
    : !status.enabled
      ? { label: 'Off', variant: 'secondary' as const }
      : job
        ? { label: 'Running', variant: 'info' as const }
        : { label: 'Idle', variant: 'secondary' as const }

  return (
    <section
      aria-label="AV1 compression queue"
      className="rounded-xl border border-border bg-card overflow-hidden"
    >
      <div className="px-4 py-3 border-b border-border flex flex-wrap items-center gap-2">
        <Minimize2 className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        <h2 className="text-base font-semibold text-foreground">AV1 compression</h2>
        <Badge variant={state.variant} size="sm">{state.label}</Badge>
        <div className="flex-1" />
        {status.available && status.enabled && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => compressExisting.mutate()}
            disabled={compressExisting.isPending}
          >
            Compress existing
          </Button>
        )}
        <Button
          variant="plain"
          size="sm-icon"
          nativeButton={false}
          render={<Link to="/settings" aria-label="Compression settings" />}
        >
          <SettingsIcon />
        </Button>
      </div>

      <div className="p-4 space-y-4">
        {!status.available && (
          <p className="text-sm text-warning">
            This server's ffmpeg has no AV1 encoder (libsvtav1), so recordings are kept as captured.
          </p>
        )}

        {job ? (
          <div className="space-y-2">
            <div className="flex items-start gap-2">
              <Loader2 className="h-4 w-4 mt-0.5 shrink-0 animate-spin motion-reduce:animate-none text-primary-ink" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground truncate">
                  {job.username ?? 'Recording'}{' '}
                  <Link to={`/watch/${job.recording_id}`} className="text-muted-foreground font-normal hover:underline">
                    {job.filename}
                  </Link>
                </p>
                <p className="text-xs text-muted-foreground">
                  {formatDuration(job.duration_seconds)} of video · {formatBytes(job.file_size)}
                </p>
              </div>
            </div>
            <Progress value={pct}>
              <ProgressLabel className="text-xs text-muted-foreground">
                {job.speed
                  ? `${job.speed.toFixed(1)}× real time · about ${formatEta(job.eta_seconds)} left`
                  : `Starting… ${formatEta(job.elapsed_seconds)} elapsed`}
              </ProgressLabel>
              <ProgressValue className="text-xs">{() => `${pct}%`}</ProgressValue>
            </Progress>
          </div>
        ) : (
          status.available && status.enabled && (
            <p className="text-sm text-muted-foreground">Nothing is being compressed right now.</p>
          )
        )}

        {status.queue_length > 0 && (
          <div className="space-y-2">
            <div className="flex items-baseline justify-between gap-2">
              <h3 className="text-sm font-medium text-foreground">
                Up next <span className="text-muted-foreground font-normal">({status.queue_length})</span>
              </h3>
              {status.eta_all_seconds != null && (
                <span className="text-xs text-muted-foreground">
                  All done in about {formatEta(status.eta_all_seconds)}
                </span>
              )}
            </div>
            <ol className="divide-y divide-border rounded-lg border border-border">
              {status.queue.slice(0, QUEUE_PREVIEW).map((item, i) => (
                <li key={item.recording_id} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <span className="w-5 text-right tabular-nums text-muted-foreground">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-foreground">{item.username ?? 'Recording'}</p>
                    <p className="truncate text-xs text-muted-foreground">{item.filename}</p>
                  </div>
                  <span className="text-xs text-muted-foreground tabular-nums whitespace-nowrap">
                    {formatDuration(item.duration_seconds)} · {formatBytes(item.file_size)}
                  </span>
                </li>
              ))}
            </ol>
            {status.queue_length > QUEUE_PREVIEW && (
              <p className="text-xs text-muted-foreground">
                and {status.queue_length - QUEUE_PREVIEW} more
              </p>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
