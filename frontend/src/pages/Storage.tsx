import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Database,
  HardDrive,
  Trash2,
  Archive,
  Loader2,
  ArrowLeft,
  User,
  Video,
  Crown,
  AlertCircle,
} from 'lucide-react'
import { Button } from '@/components/selia/button'
import { IconBox } from '@/components/selia/icon-box'
import { StaggerContainer, StaggerItem } from '@/components/motion'
import { api, type StorageStats } from '@/lib/api'
import { formatBytes, formatDuration, cn } from '@/lib/utils'
import { useDateFormat } from '@/lib/timezone-context'
import { useConfirm } from '@/components/ConfirmDialog'
import QueryError from '@/components/QueryError'
import toast from 'react-hot-toast'

export default function Storage() {
  const fmt = useDateFormat()
  const { confirm, confirmDialog } = useConfirm()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<Set<number>>(new Set())

  const { data: overview, isLoading: overviewLoading, isError: overviewError, error: overviewErr, refetch: refetchOverview } = useQuery({
    queryKey: ['statsOverview'],
    queryFn: () => api.stats.overview(),
  })

  const { data: storageStats, isLoading: statsLoading } = useQuery<StorageStats>({
    queryKey: ['storageStats'],
    queryFn: () => api.stats.storage(),
  })

  const { data: byUser, isLoading: byUserLoading } = useQuery({
    queryKey: ['storageByUser'],
    queryFn: () => api.stats.storageByUser(50),
  })

  const { data: largest, isLoading: largestLoading } = useQuery({
    queryKey: ['largestRecordings'],
    queryFn: () => api.stats.largestRecordings(25),
  })

  const compressMutation = useMutation({
    mutationFn: (ids: number[]) => api.recordings.batchCompress(ids),
    onSuccess: (res) => {
      toast.success(`Compressed ${res.compressed} recordings`)
      invalidateAll()
      setSelected(new Set())
    },
    onError: (e: Error) => toast.error(e.message || 'Compress failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: (ids: number[]) => api.recordings.batchDelete(ids),
    onSuccess: (res) => {
      toast.success(`Deleted ${res.deleted} recordings`)
      invalidateAll()
      setSelected(new Set())
    },
    onError: (e: Error) => toast.error(e.message || 'Delete failed'),
  })

  const cleanupMutation = useMutation({
    mutationFn: () => api.settings.runCleanup(),
    onSuccess: (res) => {
      toast.success(`Cleanup complete: ${res.deleted} deleted, ${res.compressed} compressed`)
      invalidateAll()
      // The rows behind these ids may be gone now; keeping them selected would
      // aim the next bulk action at recordings the user can no longer see.
      setSelected(new Set())
    },
    onError: (e: Error) => toast.error(e.message || 'Cleanup failed'),
  })

  const selectedSize = (largest ?? [])
    .filter((r) => selected.has(r.id))
    .reduce((sum, r) => sum + (r.file_size ?? 0), 0)

  const handleRunCleanup = async () => {
    // Pull the preview first so the prompt can name what is about to go.
    const stats = await api.settings.getCleanupStats().catch(() => null)
    const ok = await confirm({
      title: 'Run storage cleanup?',
      description: stats
        ? `This applies your retention policy to recordings older than ${stats.days} days and cannot be undone.`
        : 'This applies your retention policy to old recordings and cannot be undone.',
      body: stats ? (
        <p className="text-sm text-muted-foreground">
          <span className="font-semibold text-foreground">{stats.count} recording(s)</span> totalling{' '}
          <span className="font-semibold text-foreground">{formatBytes(stats.total_size)}</span> match the
          policy and will be deleted or compressed.
        </p>
      ) : undefined,
      confirmLabel: 'Run Cleanup',
    })
    if (ok) cleanupMutation.mutate()
  }

  const handleCompressSelected = async () => {
    const ok = await confirm({
      title: `Compress ${selected.size} recording(s)?`,
      description: 'The original files are rewritten in place. This cannot be undone.',
      body: (
        <p className="text-sm text-muted-foreground">
          Currently using <span className="font-semibold text-foreground">{formatBytes(selectedSize)}</span>.
        </p>
      ),
      confirmLabel: 'Compress',
    })
    if (ok) compressMutation.mutate(Array.from(selected))
  }

  const handleDeleteSelected = async () => {
    const ok = await confirm({
      title: `Delete ${selected.size} recording(s)?`,
      description: 'The recordings and their files will be permanently deleted. This cannot be undone.',
      body: (
        <p className="text-sm text-muted-foreground">
          This will free <span className="font-semibold text-foreground">{formatBytes(selectedSize)}</span>.
        </p>
      ),
      confirmLabel: 'Delete',
    })
    if (ok) deleteMutation.mutate(Array.from(selected))
  }

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['statsOverview'] })
    queryClient.invalidateQueries({ queryKey: ['storageStats'] })
    queryClient.invalidateQueries({ queryKey: ['storageByUser'] })
    queryClient.invalidateQueries({ queryKey: ['largestRecordings'] })
    queryClient.invalidateQueries({ queryKey: ['recordings'] })
  }

  const toggleSelect = (id: number) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  const total = storageStats?.total_storage ?? overview?.total_storage ?? 0
  const recordingBytes = storageStats?.recording_storage ?? 0
  const clipBytes = storageStats?.clip_storage ?? overview?.clip_storage ?? 0

  const isLoading = overviewLoading || statsLoading || byUserLoading || largestLoading
  const loadingRows = 6

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-muted-foreground mb-1">
            <Button
              variant="plain"
              size="sm"
              onClick={() => navigate(-1)}
              className="h-8 px-2 -ml-2"
            >
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <IconBox variant="secondary-subtle" size="sm">
              <Database className="h-3.5 w-3.5" />
            </IconBox>
            <span className="text-sm font-medium">Storage</span>
          </div>
          <h1 className="text-2xl font-bold text-foreground tracking-tight">Storage Management</h1>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleRunCleanup}
            disabled={cleanupMutation.isPending}
          >
            {cleanupMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin mr-1.5" /> : <Archive className="h-4 w-4 mr-1.5" />}
            Run Cleanup
          </Button>
        </div>
      </div>

      {overviewError ? (
        <QueryError error={overviewErr} what="storage stats" onRetry={() => refetchOverview()} />
      ) : (
      <>
      {/* Headline stats */}
        <StaggerContainer className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StaggerItem>
            <div className="rounded-xl border border-border bg-card p-4">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-lg bg-primary-subtle flex items-center justify-center">
                  <HardDrive className="h-5 w-5 text-primary-ink" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-foreground">{formatBytes(total)}</p>
                  <p className="text-xs text-muted-foreground">Total used</p>
                </div>
              </div>
            </div>
          </StaggerItem>
          <StaggerItem>
            <div className="rounded-xl border border-border bg-card p-4">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-lg bg-info/15 flex items-center justify-center">
                  <Video className="h-5 w-5 text-info" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-foreground">{formatBytes(recordingBytes)}</p>
                  <p className="text-xs text-muted-foreground">Recordings</p>
                </div>
              </div>
            </div>
          </StaggerItem>
          <StaggerItem>
            <div className="rounded-xl border border-border bg-card p-4">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-lg bg-primary-subtle flex items-center justify-center">
                  <Crown className="h-5 w-5 text-primary-ink" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-foreground">{formatBytes(clipBytes)}</p>
                  <p className="text-xs text-muted-foreground">Clips</p>
                </div>
              </div>
            </div>
          </StaggerItem>
          <StaggerItem>
            <div className="rounded-xl border border-border bg-card p-4">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-lg bg-warning/15 flex items-center justify-center">
                  <Archive className="h-5 w-5 text-warning" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-foreground">{formatBytes(storageStats?.backup_storage ?? 0)}</p>
                  <p className="text-xs text-muted-foreground">Backups</p>
                </div>
              </div>
            </div>
          </StaggerItem>
        </StaggerContainer>

        {/* Per-user breakdown */}
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <h2 className="text-base font-semibold text-foreground">Storage by User</h2>
            <p className="text-xs text-muted-foreground">Top users by disk usage</p>
          </div>
          <div className="max-h-[420px] overflow-y-auto">
            {isLoading ? (
              <div className="p-4 space-y-3">
                {Array.from({ length: loadingRows }).map((_, i) => (
                  <div key={i} className="h-12 rounded-lg bg-secondary animate-pulse" />
                ))}
              </div>
            ) : (byUser?.length ?? 0) === 0 ? (
              <div className="p-10 text-center">
                <User className="h-10 w-10 mx-auto text-muted-foreground/40 mb-2" />
                <p className="text-sm text-muted-foreground">No user data yet</p>
              </div>
            ) : (
              <table className="w-full text-sm text-left">
                <thead className="bg-secondary text-xs uppercase text-muted-foreground sticky top-0">
                  <tr>
                    <th className="px-4 py-2 font-medium">User</th>
                    <th className="px-4 py-2 font-medium text-right">Recordings</th>
                    <th className="px-4 py-2 font-medium text-right">Storage</th>
                    <th className="px-4 py-2 font-medium text-right">% of total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {byUser?.map((u) => (
                    <tr key={u.user_id} className="hover:bg-accent/40 transition-colors">
                      <td className="px-4 py-3 font-medium text-foreground">
                        <span className="inline-flex items-center gap-2">
                          <User className="h-3.5 w-3.5 text-muted-foreground" />
                          {u.username}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">{u.count}</td>
                      <td className="px-4 py-3 text-right tabular-nums font-medium">{formatBytes(u.bytes)}</td>
                      <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                        {total > 0 ? `${((u.bytes / total) * 100).toFixed(1)}%` : '0%'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Largest recordings with bulk actions */}
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="px-4 py-3 border-b border-border flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-foreground">Largest Recordings</h2>
            <div className="flex items-center gap-2">
              {selected.size > 0 && (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleCompressSelected}
                    disabled={compressMutation.isPending || deleteMutation.isPending}
                  >
                    <Archive className="h-4 w-4 mr-1.5" />
                    Compress {selected.size}
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={handleDeleteSelected}
                    disabled={compressMutation.isPending || deleteMutation.isPending}
                  >
                    <Trash2 className="h-4 w-4 mr-1.5" />
                    Delete {selected.size}
                  </Button>
                </>
              )}
            </div>
          </div>
          <div className="max-h-[500px] overflow-y-auto">
            {largestLoading ? (
              <div className="p-4 space-y-3">
                {Array.from({ length: loadingRows }).map((_, i) => (
                  <div key={i} className="h-14 rounded-lg bg-secondary animate-pulse" />
                ))}
              </div>
            ) : (largest?.length ?? 0) === 0 ? (
              <div className="p-10 text-center">
                <Video className="h-10 w-10 mx-auto text-muted-foreground/40 mb-2" />
                <p className="text-sm text-muted-foreground">No recordings to manage</p>
              </div>
            ) : (
              <table className="w-full text-sm text-left">
                <thead className="bg-secondary text-xs uppercase text-muted-foreground sticky top-0">
                  <tr>
                    <th className="px-4 py-2 w-10">
                      <span className="sr-only">Select</span>
                    </th>
                    <th className="px-4 py-2 font-medium">Recording</th>
                    <th className="px-4 py-2 font-medium">User</th>
                    <th className="px-4 py-2 font-medium text-right">Size</th>
                    <th className="px-4 py-2 font-medium text-right">Duration</th>
                    <th className="px-4 py-2 font-medium text-right">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {largest?.map((r) => (
                    <tr key={r.id} className="hover:bg-accent/40 transition-colors">
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          checked={selected.has(r.id)}
                          onChange={() => toggleSelect(r.id)}
                          className="h-4 w-4 rounded border-border text-primary-ink focus:ring-primary"
                        />
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => navigate(`/watch/${r.id}`)}
                          className="text-left font-medium text-foreground hover:text-primary-ink hover:underline"
                        >
                          {r.filename}
                        </button>
                        <p className="text-xs text-muted-foreground">{fmt(r.created_at)}</p>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{r.username}</td>
                      <td className="px-4 py-3 text-right tabular-nums font-medium">{formatBytes(r.file_size)}</td>
                      <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                        {r.duration_seconds ? formatDuration(r.duration_seconds) : '—'}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className={cn(
                          'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium',
                          r.status === 'completed' && 'bg-success/10 text-success',
                          r.status === 'recording' && 'bg-danger/15 text-danger',
                          r.status === 'compressed' && 'bg-warning/15 text-warning',
                          !['completed', 'recording', 'compressed'].includes(r.status) && 'bg-secondary text-muted'
                        )}>
                          {r.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Info note */}
        <div className="flex items-start gap-3 rounded-lg border border-border bg-secondary p-3 text-sm text-muted-foreground">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <p>
            Compress moves original recordings to a backup archive and replaces them with smaller remuxed versions. Deleted recordings are removed permanently.
          </p>
        </div>
      </>
      )}

      {confirmDialog}
    </div>
  )
}
