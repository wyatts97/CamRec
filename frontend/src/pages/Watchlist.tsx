import { useState, useMemo, useCallback, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus,
  RefreshCw,
  Trash2,
  Play,
  Eye,
  EyeOff,
  Search,
  Users,
  ExternalLink,
  Film,
  Loader2,
  Ban,
  Upload,
  ClipboardList,
  Check,
  X,
  StopCircle,
  ChevronLeft,
  ChevronRight,
  Radar,
} from 'lucide-react'
import { Button } from 'components/selia/button'
import { Badge } from 'components/selia/badge'
import { Input } from 'components/selia/input'
import { Label } from 'components/selia/label'
import {
  Dialog,
  DialogTrigger,
  DialogPopup,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogBody,
  DialogFooter,
} from 'components/selia/dialog'
import {
  Drawer,
  DrawerPopup,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
  DrawerBody,
} from 'components/selia/drawer'
import { api, type Recording } from '@/lib/api'
import { useDateFormat } from '@/lib/timezone-context'
import { useConfirm } from '@/components/ConfirmDialog'
import toast from 'react-hot-toast'
import EmptyState from '@/components/EmptyState'
import QueryError from '@/components/QueryError'
import { Checkbox } from 'components/selia/checkbox'
import WatchlistProfileCard from '@/components/WatchlistProfileCard'
import { timeAgo } from '@/lib/notifications'
import { profileUrl, roomStateLabel, siteLabel } from '@/lib/sites'

const PER_PAGE = 20

function formatCountdown(seconds: number): string {
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`
  return `${Math.round(seconds / 60)}m`
}

export default function Watchlist() {
  const fmt = useDateFormat()
  const { confirm, confirmDialog } = useConfirm()
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [importDialogOpen, setImportDialogOpen] = useState(false)
  const [importText, setImportText] = useState('')
  const [importStatus, setImportStatus] = useState<string | null>(null)
  const [newUsername, setNewUsername] = useState('')
  const [isMonitoring, setIsMonitoring] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [detailUserId, setDetailUserId] = useState<number | null>(null)
  const [page, setPage] = useState(1)
  const queryClient = useQueryClient()
  const retriedIdsRef = useRef<Set<number>>(new Set())

  const { data: users = [], isLoading, isError, error, refetch } = useQuery({
    queryKey: ['users'],
    queryFn: () => api.users.list(),
  })

  // Shared cache with the sidebar/dashboard; drives the REC badge and Watch button.
  const { data: activeRecordings = [] } = useQuery({
    queryKey: ['activeRecordings'],
    queryFn: () => api.recordings.getActive(),
    refetchInterval: 30000,
  })

  // "Check now" moved here from the old sidebar countdown.
  const { data: monitorStatus } = useQuery({
    queryKey: ['monitorStatus'],
    queryFn: () => api.settings.getMonitorStatus(),
    refetchInterval: 15000,
  })

  const checkNowMutation = useMutation({
    mutationFn: () => api.settings.triggerMonitorCheck(),
    onSuccess: () => {
      toast.success('Checking your watchlist for live streams')
      queryClient.invalidateQueries({ queryKey: ['monitorStatus'] })
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ['users'] }), 5000)
    },
    onError: (error: Error) => toast.error(error.message),
  })

  const { data: detailUser } = useQuery({
    queryKey: ['user', detailUserId],
    queryFn: () => api.users.get(detailUserId!),
    enabled: detailUserId !== null,
  })

  const { data: userRecordings } = useQuery({
    queryKey: ['recordings', 'user', detailUserId],
    queryFn: () => api.recordings.list(1, 20, undefined, detailUserId!),
    enabled: detailUserId !== null,
  })

  const addUserMutation = useMutation({
    mutationFn: (data: { username: string; isMonitoring: boolean }) =>
      api.users.create(data.username, data.isMonitoring),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setAddDialogOpen(false)
      setNewUsername('')
      setIsMonitoring(false)
      toast.success('Model added')
    },
    onError: (error: Error) => {
      toast.error(error.message)
    },
  })

  const removeFromWatchlistMutation = useMutation({
    mutationFn: (id: number) => api.users.removeFromWatchlist(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setSelectedIds(new Set())
      toast.success('Model removed')
    },
    onError: (error: Error) => {
      toast.error(error.message)
    },
  })

  const refreshUserMutation = useMutation({
    mutationFn: (id: number) => api.users.refresh(id, true),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      queryClient.invalidateQueries({ queryKey: ['user', id] })
    },
    onError: (error: Error) => {
      toast.error(error.message)
    },
  })

  const toggleMonitoringMutation = useMutation({
    mutationFn: ({ id, isMonitoring }: { id: number; isMonitoring: boolean }) =>
      api.users.update(id, { is_monitoring: isMonitoring }),
    // Optimistic update so the switch responds instantly; roll back on error.
    onMutate: async ({ id, isMonitoring }) => {
      await queryClient.cancelQueries({ queryKey: ['users'] })
      const previous = queryClient.getQueryData(['users'])
      queryClient.setQueryData(['users'], (old: any) => {
        if (!Array.isArray(old)) return old
        return old.map((u: any) => (u.id === id ? { ...u, is_monitoring: isMonitoring } : u))
      })
      return { previous }
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['users'], context.previous)
      }
      toast.error('Failed to update monitoring')
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
    },
  })

  const handleStopAll = async () => {
    const ok = await confirm({
      title: 'Stop all active recordings?',
      description: 'Every in-flight recording is ended immediately. Captured footage is kept, but recording does not resume on its own.',
      confirmLabel: 'Stop All',
    })
    if (ok) stopAllMutation.mutate()
  }

  const handleRemoveOne = async (id: number, username: string) => {
    const ok = await confirm({
      title: `Remove ${username} from the watchlist?`,
      description: 'They will no longer be monitored for live streams. Existing recordings are kept.',
      confirmLabel: 'Remove',
    })
    if (ok) removeFromWatchlistMutation.mutate(id)
    return ok
  }

  const handleRemoveSelected = async () => {
    const ok = await confirm({
      title: `Remove ${selectedIds.size} user(s) from the watchlist?`,
      description: 'They will no longer be monitored for live streams. Existing recordings are kept.',
      confirmLabel: 'Remove',
    })
    if (ok) batchRemoveMutation.mutate(Array.from(selectedIds))
  }

  const startRecordingMutation = useMutation({
    mutationFn: (username: string) => api.recordings.start({ username }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recordings'] })
      queryClient.invalidateQueries({ queryKey: ['activeRecordings'] })
      toast.success('Recording started')
    },
    onError: (error: Error) => {
      toast.error(error.message)
    },
  })

  const batchRemoveMutation = useMutation({
    mutationFn: (ids: number[]) => Promise.all(ids.map((id) => api.users.removeFromWatchlist(id))),
    onSuccess: (_res, ids) => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setSelectedIds(new Set())
      toast.success(`Removed ${ids.length} user(s)`)
    },
    onError: (error: Error) => toast.error(error.message),
  })

  const batchToggleMonitoring = useMutation({
    mutationFn: ({ ids, monitoring }: { ids: number[]; monitoring: boolean }) =>
      Promise.all(ids.map((id) => api.users.update(id, { is_monitoring: monitoring }))),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setSelectedIds(new Set())
      toast.success('Monitoring settings updated')
    },
    onError: (error: Error) => {
      toast.error(error.message)
    },
  })

  const stopAllMutation = useMutation({
    mutationFn: () => api.recordings.stopAll(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['recordings'] })
      queryClient.invalidateQueries({ queryKey: ['activeRecordings'] })
      toast.success(`${data.stopped} recording(s) stopped`)
    },
    onError: (error: Error) => {
      toast.error(error.message)
    },
  })

  const handleAddUser = (e: React.FormEvent) => {
    e.preventDefault()
    if (newUsername.trim()) {
      addUserMutation.mutate({ username: newUsername.trim(), isMonitoring })
    }
  }

  const [refreshingAll, setRefreshingAll] = useState(false)

  const handleRefreshAll = async () => {
    if (refreshingAll) return
    setRefreshingAll(true)
    let ok = 0
    let failed = 0
    try {
      for (const user of users) {
        // Per-user try/catch: one unreachable profile must not abandon the
        // rest of the watchlist half-refreshed.
        try {
          await refreshUserMutation.mutateAsync(user.id)
          ok++
        } catch {
          failed++
        }
      }
    } finally {
      setRefreshingAll(false)
    }
    if (failed === 0) toast.success(`Refreshed ${ok} user(s)`)
    else toast.error(`Refreshed ${ok} user(s), ${failed} failed`)
  }

  const filteredUsers = useMemo(() => {
    const sorted = [...users].sort((a, b) => {
      if (a.is_live === b.is_live) return 0
      return a.is_live ? -1 : 1
    })
    if (!searchQuery.trim()) return sorted
    const q = searchQuery.toLowerCase()
    return sorted.filter(
      (u) =>
        u.username.toLowerCase().includes(q) ||
        (u.display_name && u.display_name.toLowerCase().includes(q))
    )
  }, [users, searchQuery])

  const selectedCount = selectedIds.size
  const pageUsers = filteredUsers.slice((page - 1) * PER_PAGE, page * PER_PAGE)
  const selectedOnPage = pageUsers.filter((u) => selectedIds.has(u.id)).length
  const recordingByUser = new Map(activeRecordings.map((r) => [r.user_id, r]))

  // Export: copy the model name list to the clipboard
  const handleExport = useCallback(() => {
    const list = users.map((u) => u.username).join('\n')
    // Use textarea fallback for insecure contexts (Docker/nginx)
    const textarea = document.createElement('textarea')
    textarea.value = list
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    try {
      document.execCommand('copy')
      toast.success('Model names copied to clipboard')
    } catch {
      toast.error('Export failed')
    }
    document.body.removeChild(textarea)
  }, [users, toast])

  // Import: parse a list of model names / profile URLs and add them
  const handleImport = useCallback(() => {
    if (!importText.trim()) return
    setImportStatus(null)
    const usernames = importText
      .split('\n')
      .map((line) => line.trim().replace(/^@/, '').replace(/\s.*$/, ''))
      .filter(Boolean)
    if (usernames.length === 0) {
      setImportStatus('No valid usernames found')
      return
    }
    let completed = 0
    const failedNames: string[] = []
    const run = async () => {
      for (const username of usernames) {
        try {
          await api.users.create(username, true)
          completed++
        } catch {
          failedNames.push(username)
        }
      }
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setImportText('')
      if (failedNames.length === 0) {
        setImportDialogOpen(false)
        setImportStatus(null)
        toast.success(`Added ${completed} model(s) to your watchlist`)
      } else {
        // Keep the dialog open and name the failures -- reporting them through
        // a success toast gave the user nothing to act on.
        const preview = failedNames.slice(0, 5).join(', ')
        const more = failedNames.length > 5 ? ` and ${failedNames.length - 5} more` : ''
        setImportStatus(`Added ${completed}; ${failedNames.length} failed: ${preview}${more}`)
        toast.error(`${failedNames.length} of ${usernames.length} user(s) failed to import`)
      }
    }
    void run()
  }, [importText, queryClient])

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 2xl:flex-row 2xl:items-start 2xl:justify-between">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-foreground tracking-tight">Watchlist</h1>
          <p className="text-muted-foreground mt-1">
            Flirt4Free models you want to monitor and record
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Dialog open={importDialogOpen} onOpenChange={setImportDialogOpen}>
            <DialogTrigger>
              <Button variant="outline">
                <Upload className="h-4 w-4 mr-2" />
                Import
              </Button>
            </DialogTrigger>
            <DialogPopup>
              <DialogHeader>
                <DialogTitle>Import Users</DialogTitle>
                <DialogDescription>
                  Paste model names or profile URLs, one per line, to add them to your watchlist with monitoring enabled.
                </DialogDescription>
              </DialogHeader>
              <DialogBody>
                <textarea
                  className="w-full min-h-[160px] rounded-lg border border-input-border bg-background p-3 text-sm font-mono resize-y focus:outline-none focus:ring-2 focus:ring-primary-border"
                  placeholder={`model-one\nhttps://www.flirt4free.com/?model=model-two`}
                  value={importText}
                  onChange={(e) => { setImportText(e.target.value); setImportStatus(null) }}
                />
                {importStatus && (
                  <div className={`mt-2 text-sm flex items-center gap-1.5 ${importStatus.includes('failed') ? 'text-danger' : 'text-success'}`}>
                    {importStatus.includes('failed') ? <X className="h-3.5 w-3.5" /> : <Check className="h-3.5 w-3.5" />}
                    {importStatus}
                  </div>
                )}
              </DialogBody>
              <DialogFooter>
                <Button variant="outline" onClick={() => { setImportDialogOpen(false); setImportText(''); setImportStatus(null) }}>
                  Cancel
                </Button>
                <Button onClick={handleImport} disabled={!importText.trim()}>
                  <Upload className="h-4 w-4 mr-2" />
                  Import {importText.trim() ? `(${importText.split('\n').filter(Boolean).length})` : ''}
                </Button>
              </DialogFooter>
            </DialogPopup>
          </Dialog>
          <Button
            variant="outline"
            onClick={() => checkNowMutation.mutate()}
            disabled={checkNowMutation.isPending || users.length === 0}
            title={monitorStatus?.last_check_at ? `Last check ${timeAgo(monitorStatus.last_check_at)}` : undefined}
          >
            {checkNowMutation.isPending ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin motion-reduce:animate-none" />
            ) : (
              <Radar className="h-4 w-4 mr-2" />
            )}
            Check now
            {monitorStatus?.next_check_in_seconds != null && !checkNowMutation.isPending && (
              <span className="text-dimmed font-normal tabular-nums">
                · {formatCountdown(monitorStatus.next_check_in_seconds)}
              </span>
            )}
          </Button>
          <Button variant="outline" onClick={handleExport} disabled={users.length === 0}>
            <ClipboardList className="h-4 w-4 mr-2" />
            Export
          </Button>
          <Button
            variant="outline"
            onClick={() => { void handleRefreshAll() }}
            disabled={users.length === 0 || refreshingAll}
          >
            {refreshingAll ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin motion-reduce:animate-none" />
            ) : (
              <RefreshCw className="h-4 w-4 mr-2" />
            )}
            {refreshingAll ? 'Refreshing…' : 'Refresh All'}
          </Button>
          <Button
            variant="danger"
            onClick={handleStopAll}
            disabled={stopAllMutation.isPending}
          >
            {stopAllMutation.isPending ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <StopCircle className="h-4 w-4 mr-2" />
            )}
            Stop Recording All
          </Button>
          <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
            <DialogTrigger>
              <Button>
                <Plus className="h-4 w-4 mr-2" />
                Add Model
              </Button>
            </DialogTrigger>
            <DialogPopup>
              <form onSubmit={handleAddUser}>
                <DialogHeader>
                  <DialogTitle>Add Model to Watchlist</DialogTitle>
                  <DialogDescription>
                    Enter a Flirt4Free model name or paste their profile URL
                  </DialogDescription>
                </DialogHeader>
                <DialogBody>
                  <div className="grid gap-4 py-4">
                    <div className="grid gap-2">
                      <Label htmlFor="username">Username</Label>
                      <Input
                        id="username"
                        placeholder="model-name or flirt4free.com URL"
                        value={newUsername}
                        onChange={(e) => setNewUsername(e.target.value)}
                      />
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        id="monitoring"
                        checked={isMonitoring}
                        onChange={(e) => setIsMonitoring(e.target.checked)}
                        className="rounded border-input-border"
                      />
                      <Label htmlFor="monitoring" className="text-sm font-normal">
                        Enable automatic monitoring
                      </Label>
                    </div>
                  </div>
                </DialogBody>
                <DialogFooter>
                  <Button type="button" variant="outline" onClick={() => setAddDialogOpen(false)}>
                    Cancel
                  </Button>
                  <Button type="submit" disabled={addUserMutation.isPending}>
                    {addUserMutation.isPending ? 'Adding...' : 'Add Model'}
                  </Button>
                </DialogFooter>
              </form>
            </DialogPopup>
          </Dialog>
        </div>
      </div>

      <section aria-label="Watchlist models">
        <div className="mb-4">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <h2 className="text-xl font-semibold tracking-tight text-foreground">
              Models <span className="text-dimmed font-normal">({filteredUsers.length})</span>
            </h2>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search models…"
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value)
                  // Without this, filtering while on page 2 slices past the end
                  // of the results: a header with no rows, no empty state, and
                  // no pager to get back with.
                  setPage(1)
                }}
                className="pl-9 h-9 w-full sm:w-64"
              />
            </div>
          </div>
        </div>
        <div>
          {selectedCount > 0 && (
            <div className="flex items-center gap-2 mb-4 p-3 rounded-lg bg-secondary">
              <span className="text-sm font-medium mr-2">{selectedCount} selected</span>
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  batchToggleMonitoring.mutate({
                    ids: Array.from(selectedIds),
                    monitoring: true,
                  })
                }
              >
                <Eye className="h-3 w-3 mr-1" />
                Enable Monitoring
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  batchToggleMonitoring.mutate({
                    ids: Array.from(selectedIds),
                    monitoring: false,
                  })
                }
              >
                <EyeOff className="h-3 w-3 mr-1" />
                Disable Monitoring
              </Button>
              <Button
                size="sm"
                variant="danger"
                onClick={handleRemoveSelected}
                disabled={batchRemoveMutation.isPending}
              >
                <Trash2 className="h-3 w-3 mr-1" />
                Remove
              </Button>
              <Button
                size="sm"
                variant="plain"
                onClick={() => setSelectedIds(new Set())}
              >
                Clear
              </Button>
            </div>
          )}

          {isError ? (
            <QueryError error={error} what="your watchlist" onRetry={() => refetch()} />
          ) : isLoading ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {Array.from({ length: 8 }, (_, i) => (
                <div key={i} className="h-80 rounded-xl bg-secondary animate-pulse motion-reduce:animate-none" />
              ))}
            </div>
          ) : filteredUsers.length === 0 ? (
            <EmptyState
              icon={Users}
              title={searchQuery ? 'No models match your search' : 'No models in your watchlist'}
              description={searchQuery ? 'Try a different search term' : 'Add Flirt4Free models to start monitoring their shows'}
              actionLabel={searchQuery ? undefined : 'Add your first model'}
              onAction={searchQuery ? undefined : () => setAddDialogOpen(true)}
            />
          ) : (
            <>
              <div className="flex items-center justify-between gap-3 mb-4">
                <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
                  <Checkbox
                    checked={pageUsers.length > 0 && selectedOnPage === pageUsers.length}
                    indeterminate={selectedOnPage > 0 && selectedOnPage < pageUsers.length}
                    onCheckedChange={(checked) =>
                      setSelectedIds(checked ? new Set(pageUsers.map((u) => u.id)) : new Set())
                    }
                    aria-label="Select all models on this page"
                  />
                  Select page
                </label>
                <span className="text-sm text-dimmed">
                  {filteredUsers.filter((u) => u.is_live).length} live · {filteredUsers.filter((u) => u.is_monitoring).length} monitored
                </span>
              </div>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {pageUsers.map((user) => (
                  <WatchlistProfileCard
                    key={user.id}
                    user={user}
                    recording={recordingByUser.get(user.id)}
                    selected={selectedIds.has(user.id)}
                    onSelectedChange={(checked) => {
                      const next = new Set(selectedIds)
                      if (checked) next.add(user.id)
                      else next.delete(user.id)
                      setSelectedIds(next)
                    }}
                    onOpen={() => setDetailUserId(user.id)}
                    onToggleMonitoring={(monitoring) =>
                      toggleMonitoringMutation.mutate({ id: user.id, isMonitoring: monitoring })
                    }
                    onRefresh={() => refreshUserMutation.mutate(user.id)}
                    onRecord={() => startRecordingMutation.mutate(user.username)}
                    onRemove={() => { void handleRemoveOne(user.id, user.username) }}
                    onAvatarError={() => {
                      if (retriedIdsRef.current.has(user.id)) return
                      retriedIdsRef.current.add(user.id)
                      api.users.refresh(user.id, true).catch(() => {})
                    }}
                  />
                ))}
              </div>

              {/* Pagination */}
              {filteredUsers.length > PER_PAGE && (
                <div className="flex items-center justify-between pt-4 mt-4 border-t border-border">
                  <span className="text-sm text-dimmed">
                    {(page - 1) * PER_PAGE + 1}–{Math.min(page * PER_PAGE, filteredUsers.length)} of {filteredUsers.length}
                  </span>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="outline"
                      size="sm-icon"
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page === 1}
                      aria-label="Previous page"
                    >
                      <ChevronLeft />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm-icon"
                      onClick={() => setPage((p) => Math.min(Math.ceil(filteredUsers.length / PER_PAGE), p + 1))}
                      disabled={page * PER_PAGE >= filteredUsers.length}
                      aria-label="Next page"
                    >
                      <ChevronRight />
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </section>

      {/* User Detail Drawer */}
      <Drawer open={detailUserId !== null} onOpenChange={(open) => { if (!open) setDetailUserId(null) }}>
        <DrawerPopup direction="right" className="overflow-y-auto">
          <DrawerHeader>
            <DrawerTitle>
              {detailUser ? detailUser.display_name || detailUser.username : 'Model Details'}
            </DrawerTitle>
            <DrawerDescription>
              {detailUser ? `${detailUser.username} · ${siteLabel(detailUser.site)}` : ''}
            </DrawerDescription>
          </DrawerHeader>

          <DrawerBody>
          {detailUser ? (
            <div className="mt-6 space-y-6">
              {/* Avatar */}
              <div className="flex justify-center">
                <div className="h-24 w-24 rounded-full bg-primary-subtle overflow-hidden">
                  <img
                    src={api.users.getAvatarUrl(detailUser.id)}
                    alt={detailUser.username}
                    className="h-full w-full object-cover"
                    loading="lazy"
                    decoding="async"
                    onError={(e) => {
                      const img = e.target as HTMLImageElement
                      img.style.display = 'none'
                      const fallback = img.nextElementSibling as HTMLElement
                      if (fallback) fallback.style.display = 'flex'
                      if (!retriedIdsRef.current.has(detailUser.id)) {
                        retriedIdsRef.current.add(detailUser.id)
                        api.users.refresh(detailUser.id, true).catch(() => {})
                      }
                    }}
                  />
                  <span className="hidden h-full w-full items-center justify-center text-2xl font-medium text-primary-ink fallback-initial">
                    {detailUser.username[0].toUpperCase()}
                  </span>
                </div>
              </div>

              {/* User info */}
              <div className="space-y-3">
                <div className="text-center">
                  {detailUser.display_name && (
                    <p className="font-semibold text-lg">{detailUser.display_name}</p>
                  )}
                  <p className="text-muted-foreground">{detailUser.username}</p>
                </div>

                <div className="flex justify-center gap-4 text-sm">
                  <div className="text-center">
                    <p className="font-semibold">{siteLabel(detailUser.site)}</p>
                    <p className="text-muted-foreground text-xs">Site</p>
                  </div>
                  <div className="text-center">
                    <p className="font-semibold">{roomStateLabel(detailUser.room_state)}</p>
                    <p className="text-muted-foreground text-xs">Status</p>
                  </div>
                </div>
              </div>

              {/* Quick actions */}
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  className="flex-1"
                  onClick={() => {
                    window.open(profileUrl(detailUser.site, detailUser.username), '_blank', 'noopener,noreferrer')
                  }}
                >
                  <ExternalLink className="h-3 w-3 mr-1" />
                  Open on {siteLabel(detailUser.site)}
                </Button>
                {detailUser.is_live && (
                  <Button
                    size="sm"
                    variant="secondary"
                    className="flex-1"
                    onClick={() => startRecordingMutation.mutate(detailUser.username)}
                  >
                    <Play className="h-3 w-3 mr-1" />
                    Record Now
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  className="flex-1"
                  onClick={() =>
                    toggleMonitoringMutation.mutate({
                      id: detailUser.id,
                      isMonitoring: !detailUser.is_monitoring,
                    })
                  }
                >
                  {detailUser.is_monitoring ? (
                    <><Ban className="h-3 w-3 mr-1" /> Stop Monitoring</>
                  ) : (
                    <><Eye className="h-3 w-3 mr-1" /> Monitor</>
                  )}
                </Button>
              </div>

              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="flex-1"
                  onClick={() => refreshUserMutation.mutate(detailUser.id)}
                >
                  <RefreshCw className="h-3 w-3 mr-1" />
                  Refresh
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  className="flex-1"
                  onClick={async () => {
                    // Only close the drawer if the removal was actually confirmed.
                    if (await handleRemoveOne(detailUser.id, detailUser.username)) {
                      setDetailUserId(null)
                    }
                  }}
                >
                  <Trash2 className="h-3 w-3 mr-1" />
                  Remove
                </Button>
              </div>

              {/* Recent Recordings */}
              <div>
                <h4 className="text-sm font-medium mb-3 flex items-center gap-2">
                  <Film className="h-4 w-4" />
                  Recent Recordings
                </h4>
                {!userRecordings ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  </div>
                ) : userRecordings.recordings.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-4">
                    No recordings for this user yet
                  </p>
                ) : (
                  <div className="space-y-2">
                    {userRecordings.recordings.slice(0, 10).map((rec: Recording) => (
                      <div
                        key={rec.id}
                        className="flex items-center gap-3 p-2 rounded-lg hover:bg-accent cursor-pointer transition-colors"
                        onClick={() => {
                          window.open(`/watch/${rec.id}`, '_blank')
                        }}
                      >
                        <div className="h-10 w-14 rounded bg-secondary overflow-hidden shrink-0 relative">
                          {rec.thumbnail_ready ? (
                            <>
                              <img
                                src={api.recordings.getThumbnailUrl(
                                  rec.id,
                                  rec.file_size ?? rec.created_at,
                                )}
                                alt=""
                                className="h-full w-full object-cover"
                                loading="lazy"
                                decoding="async"
                                onError={(e) => {
                                  const img = e.target as HTMLImageElement
                                  img.style.display = 'none'
                                  const fallback = img.nextElementSibling as HTMLElement
                                  if (fallback) fallback.classList.remove('hidden')
                                }}
                              />
                              <div className="hidden h-full w-full flex items-center justify-center absolute inset-0">
                                <Film className="h-3 w-3 text-muted-foreground" />
                              </div>
                            </>
                          ) : (
                            <div className="h-full w-full flex items-center justify-center">
                              <Film className="h-3 w-3 text-muted-foreground" />
                            </div>
                          )}
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="text-xs font-medium truncate">
                            {rec.filename || `Recording #${rec.id}`}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {fmt(rec.ended_at || rec.created_at)}
                          </p>
                        </div>
                        <Badge variant="secondary-outline" className="text-[10px] capitalize">
                          {rec.status}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          )}
        </DrawerBody>
        </DrawerPopup>
      </Drawer>
      {confirmDialog}
    </div>
  )
}
