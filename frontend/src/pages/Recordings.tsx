import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Download,
  Trash2,
  StopCircle,
  Play,
  Video,
  Loader2,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/selia/card'
import { Button } from '@/components/selia/button'
import { Badge } from '@/components/selia/badge'
import { Input } from '@/components/selia/input'
import {
  Dialog,
  DialogPopup,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogBody,
} from '@/components/selia/dialog'
import EmptyState from '@/components/EmptyState'
import QueryError from '@/components/QueryError'
import { ListSkeleton } from '@/components/Skeleton'
import { api, type Recording } from '@/lib/api'
import { downloadFiles, formatBytes, formatDuration } from '@/lib/utils'
import { useDateFormat } from '@/lib/timezone-context'
import { useConfirm } from '@/components/ConfirmDialog'
import toast from 'react-hot-toast'

const statusVariantMap: Record<string, 'secondary' | 'info' | 'success' | 'danger' | 'secondary-outline'> = {
  pending: 'secondary',
  recording: 'info',
  completed: 'success',
  failed: 'danger',
  stopped: 'secondary-outline',
}


export default function Recordings() {
  const fmt = useDateFormat()
  const { confirm, confirmDialog } = useConfirm()
  const [searchParams, setSearchParams] = useSearchParams()
  const [page, setPage] = useState(() => {
    const p = searchParams.get('page')
    return p ? parseInt(p) : 1
  })
  const perPage = (() => {
    const pp = searchParams.get('perPage')
    return pp ? parseInt(pp) : 20
  })()
  const [statusFilter, setStatusFilter] = useState<string | undefined>(() => {
    return searchParams.get('status') || undefined
  })
  const [sortBy, setSortBy] = useState(() => searchParams.get('sortBy') || 'date')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>(() => {
    return (searchParams.get('sortOrder') as 'asc' | 'desc') || 'desc'
  })
  const [usernameFilter, setUsernameFilter] = useState(() => searchParams.get('username') || '')
  const [recordDialogOpen, setRecordDialogOpen] = useState(false)
  const [newUsername, setNewUsername] = useState('')
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const queryClient = useQueryClient()
  const [isDownloading, setIsDownloading] = useState(false)

  // Sync state to URL search params
  // Selection is per-page: carrying it across pages meant "Delete" could act
  // on rows scrolled out of view.
  useEffect(() => {
    setSelectedIds(new Set())
  }, [page, statusFilter, usernameFilter, sortBy, sortOrder])

  useEffect(() => {
    const params = new URLSearchParams()
    if (page > 1) params.set('page', String(page))
    if (perPage !== 20) params.set('perPage', String(perPage))
    if (statusFilter) params.set('status', statusFilter)
    if (sortBy !== 'date') params.set('sortBy', sortBy)
    if (sortOrder !== 'desc') params.set('sortOrder', sortOrder)
    if (usernameFilter) params.set('username', usernameFilter)
    setSearchParams(params, { replace: true })
  }, [page, perPage, statusFilter, sortBy, sortOrder, usernameFilter, setSearchParams])

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['recordings', page, perPage, statusFilter, sortBy, sortOrder, usernameFilter],
    queryFn: () => api.recordings.list(page, perPage, statusFilter, undefined, {
      sortBy,
      sortOrder,
      usernameFilter: usernameFilter || undefined,
    }),
  })

  const hasActiveFilters = !!usernameFilter || !!statusFilter

  const clearFilters = useCallback(() => {
    setStatusFilter(undefined)
    setUsernameFilter('')
    setSortBy('date')
    setSortOrder('desc')
    setPage(1)
  }, [])

  const recordings = data?.recordings || []
  const total = data?.total || 0

  const startRecordingMutation = useMutation({
    mutationFn: (username: string) => api.recordings.start({ username }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recordings'] })
      queryClient.invalidateQueries({ queryKey: ['activeRecordings'] })
      setRecordDialogOpen(false)
      setNewUsername('')
      toast.success('Recording started')
    },
    onError: (error: Error) => {
      toast.error(error.message)
    },
  })

  const stopRecordingMutation = useMutation({
    mutationFn: (id: number) => api.recordings.stop(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recordings'] })
      queryClient.invalidateQueries({ queryKey: ['activeRecordings'] })
      toast.success('Recording stopped')
    },
    onError: (error: Error) => {
      toast.error(error.message)
    },
  })

  const deleteRecordingMutation = useMutation({
    mutationFn: (id: number) => api.recordings.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recordings'] })
      toast.success('Recording deleted')
    },
    onError: (error: Error) => {
      toast.error(error.message)
    },
  })

  const batchDeleteMutation = useMutation({
    mutationFn: (ids: number[]) => api.recordings.batchDelete(ids),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['recordings'] })
      setSelectedIds(new Set())
      setDeleteConfirmOpen(false)
      toast.success(`${data.deleted} recording(s) deleted${data.errors.length > 0 ? `, ${data.errors.length} error(s)` : ''}`)
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

  const handleStartRecording = (e: React.FormEvent) => {
    e.preventDefault()
    if (newUsername.trim()) {
      startRecordingMutation.mutate(newUsername.trim())
    }
  }

  const handleDownload = (recording: Recording) => {
    const a = document.createElement('a')
    a.href = api.recordings.getDownloadUrl(recording.id)
    a.download = ''
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  // Selected recordings download as individual files, one after another.
  const handleBatchDownload = async () => {
    if (selectedIds.size === 0) return
    setIsDownloading(true)
    try {
      await downloadFiles(Array.from(selectedIds).map((id) => api.recordings.getDownloadUrl(id)))
    } finally {
      setIsDownloading(false)
    }
  }

  const handleBatchDelete = () => {
    if (selectedIds.size === 0) return
    batchDeleteMutation.mutate(Array.from(selectedIds))
  }


  const handleStopAll = async () => {
    const ok = await confirm({
      title: 'Stop all active recordings?',
      description: 'Every in-flight recording is ended immediately. Captured footage is kept, but recording does not resume on its own.',
      confirmLabel: 'Stop All',
    })
    if (ok) stopAllMutation.mutate()
  }

  const handleDeleteRow = async (id: number, username: string) => {
    const ok = await confirm({
      title: `Delete recording of ${username}?`,
      description: 'The recording and its file will be permanently deleted. This cannot be undone.',
      confirmLabel: 'Delete',
    })
    if (ok) deleteRecordingMutation.mutate(id)
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-foreground tracking-tight">Recordings</h1>
          <p className="text-muted-foreground mt-1">
            View and manage your live cam recordings
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
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
          <Dialog open={recordDialogOpen} onOpenChange={setRecordDialogOpen}>
          <DialogTrigger>
            <Button>
              <Play className="h-4 w-4" />
              New Recording
            </Button>
          </DialogTrigger>
          <DialogPopup>
            <form onSubmit={handleStartRecording}>
              <DialogHeader>
                <DialogTitle>Start New Recording</DialogTitle>
                <DialogDescription>
                  Enter a Flirt4Free model name or profile URL. Only public shows can be recorded.
                </DialogDescription>
              </DialogHeader>
              <DialogBody>
                <div className="space-y-4">
                  <Input
                    placeholder="model-name or flirt4free.com URL"
                    value={newUsername}
                    onChange={(e) => setNewUsername(e.target.value)}
                  />
                </div>
              </DialogBody>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setRecordDialogOpen(false)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={startRecordingMutation.isPending}>
                  {startRecordingMutation.isPending ? 'Starting...' : 'Start Recording'}
                </Button>
              </DialogFooter>
            </form>
          </DialogPopup>
        </Dialog>
        </div>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <CardTitle className="flex items-center gap-2">
              <Video className="h-5 w-5" />
              Recordings ({total})
            </CardTitle>
            <div className="flex items-center gap-2">
              <select
                value={statusFilter || 'all'}
                onChange={(e) => { const val = e.target.value; setStatusFilter(val === 'all' ? undefined : val); setPage(1) }}
                className="h-8 px-2 text-sm rounded-lg border border-input-border bg-input text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              >
                <option value="all">All Status</option>
                <option value="recording">Recording</option>
                <option value="completed">Completed</option>
                <option value="stopped">Stopped</option>
                <option value="failed">Failed</option>
              </select>
              <input
                placeholder="Filter by user…"
                value={usernameFilter}
                onChange={(e) => { setUsernameFilter(e.target.value); setPage(1) }}
                className="h-8 px-3 text-sm rounded-lg border border-input-border bg-input text-foreground focus:outline-none focus:ring-2 focus:ring-primary w-44"
              />
              {hasActiveFilters && (
                <button
                  onClick={clearFilters}
                  className="h-8 px-2 text-xs text-muted hover:text-foreground transition-colors"
                >
                  Clear
                </button>
              )}
            </div>
          </div>
        </CardHeader>
        <CardBody>
          {selectedIds.size > 0 && recordings.length > 0 && (
            <div className="flex items-center gap-2 mb-4 p-3 bg-primary-subtle rounded-lg">
              <span className="text-sm font-medium">
                {selectedIds.size} selected
              </span>
              <div className="flex-1" />
              <Button
                size="sm"
                variant="outline"
                onClick={handleBatchDownload}
                disabled={isDownloading}
              >
                {isDownloading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Download className="h-4 w-4" />
                )}
                Download
              </Button>
              <Button
                size="sm"
                variant="danger"
                onClick={() => setDeleteConfirmOpen(true)}
              >
                <Trash2 className="h-4 w-4" />
                Delete
              </Button>
            </div>
          )}

          {isError ? (
            <QueryError error={error} what="recordings" onRetry={() => refetch()} />
          ) : isLoading ? (
            <div className="p-4"><ListSkeleton rows={8} /></div>
          ) : recordings.length === 0 ? (
            <EmptyState
              icon={Video}
              title="No recordings found"
              description="Start a recording to capture a live cam show"
              actionLabel="Start your first recording"
              onAction={() => setRecordDialogOpen(true)}
            />
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-table-separator">
                  <thead className="bg-table-head">
                    <tr>
                      <th scope="col" className="px-4 py-3 text-start">
                        <input
                          type="checkbox"
                          className="rounded border-input-border"
                          aria-label="Select all recordings on this page"
                          {...(() => {
                            const selectedOnPage = recordings.filter((r) => selectedIds.has(r.id)).length
                            return {
                              checked: recordings.length > 0 && selectedOnPage === recordings.length,
                              ref: (el: HTMLInputElement | null) => {
                                if (el) el.indeterminate = selectedOnPage > 0 && selectedOnPage < recordings.length
                              },
                            }
                          })()}
                          onChange={(e) => setSelectedIds(e.target.checked ? new Set(recordings.map((r) => r.id)) : new Set())}
                        />
                      </th>
                      <th scope="col" className="px-4 py-3 text-start text-xs font-medium text-muted uppercase tracking-wide">User</th>
                      <th scope="col" className="px-4 py-3 text-start text-xs font-medium text-muted uppercase tracking-wide">Status</th>
                      <th scope="col" className="px-4 py-3 text-start text-xs font-medium text-muted uppercase tracking-wide">Duration</th>
                      <th scope="col" className="hidden sm:table-cell px-4 py-3 text-start text-xs font-medium text-muted uppercase tracking-wide">Size</th>
                      <th scope="col" className="px-4 py-3 text-start text-xs font-medium text-muted uppercase tracking-wide">Date</th>
                      <th scope="col" className="px-4 py-3 text-end text-xs font-medium text-muted uppercase tracking-wide">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-table-separator">
                    {recordings.map((row) => (
                      <tr key={row.id} className="hover:bg-table-accent transition-colors">
                        <td className="px-4 py-3">
                          <input
                            type="checkbox"
                            className="rounded border-input-border"
                            aria-label={`Select recording ${row.filename}`}
                            checked={selectedIds.has(row.id)}
                            onChange={(e) => {
                              const next = new Set(selectedIds)
                              if (e.target.checked) next.add(row.id)
                              else next.delete(row.id)
                              setSelectedIds(next)
                            }}
                          />
                        </td>
                        <td className="px-4 py-3">
                          <span className="block text-sm font-semibold text-foreground">{row.username}</span>
                          <span className="block text-xs text-muted truncate max-w-[200px]">{row.filename}</span>
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant={statusVariantMap[row.status] || 'secondary'}>{row.status}</Badge>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-sm text-foreground">{formatDuration(row.duration_seconds)}</span>
                        </td>
                        <td className="hidden sm:table-cell px-4 py-3">
                          <span className="text-sm text-foreground">{formatBytes(row.file_size)}</span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-sm text-muted">{fmt(row.started_at || row.created_at)}</span>
                        </td>
                        <td className="px-4 py-3 text-end">
                          <div className="inline-flex rounded-lg shadow-sm">
                            {row.status === 'recording' && (
                              <button
                                title="Stop recording" aria-label="Stop recording recording"
                                className="py-1.5 px-2 inline-flex items-center -ms-px first:rounded-s-lg first:ms-0 last:rounded-e-lg text-sm font-medium focus:z-10 border border-border bg-card text-danger hover:bg-danger/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                                onClick={() => stopRecordingMutation.mutate(row.id)}
                                disabled={stopRecordingMutation.isPending}
                              >
                                <StopCircle className="h-3.5 w-3.5" />
                              </button>
                            )}
                            {(row.status === 'completed' || row.status === 'stopped') && (
                              <button
                                title="Download" aria-label="Download recording"
                                className="py-1.5 px-2 inline-flex items-center -ms-px first:rounded-s-lg first:ms-0 last:rounded-e-lg text-sm font-medium focus:z-10 border border-border bg-card text-primary-ink hover:bg-primary-subtle disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                                onClick={() => handleDownload(row)}
                              >
                                <Download className="h-3.5 w-3.5" />
                              </button>
                            )}
                            <button
                              title="Delete" aria-label={`Delete recording of ${row.username}`}
                              className="py-1.5 px-2 inline-flex items-center -ms-px first:rounded-s-lg first:ms-0 last:rounded-e-lg text-sm font-medium focus:z-10 border border-border bg-card text-danger hover:bg-danger/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                              onClick={() => handleDeleteRow(row.id, row.username)}
                              disabled={deleteRecordingMutation.isPending}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {total > perPage && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-border">
                  <span className="text-sm text-muted">
                    {(page - 1) * perPage + 1}–{Math.min(page * perPage, total)} of {total}
                  </span>
                  <div className="inline-flex rounded-lg shadow-sm">
                    <button
                      className="py-1.5 px-2 inline-flex items-center -ms-px first:rounded-s-lg first:ms-0 last:rounded-e-lg text-sm font-medium focus:z-10 border border-border bg-card text-foreground hover:bg-accent disabled:opacity-50"
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page === 1}
                      aria-label="Previous page"
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </button>
                    <button
                      className="py-1.5 px-2 inline-flex items-center -ms-px first:rounded-s-lg first:ms-0 last:rounded-e-lg text-sm font-medium focus:z-10 border border-border bg-card text-foreground hover:bg-accent disabled:opacity-50"
                      onClick={() => setPage((p) => p + 1)}
                      disabled={page * perPage >= total}
                      aria-label="Next page"
                    >
                      <ChevronRight className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardBody>
      </Card>

      <Dialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <DialogPopup>
          <DialogHeader>
            <DialogTitle>Delete {selectedIds.size} Recording(s)?</DialogTitle>
            <DialogDescription>
              This action cannot be undone. The selected recordings and their files will be permanently deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            <p className="text-sm text-muted-foreground">Are you sure you want to delete {selectedIds.size} recording(s)?</p>
          </DialogBody>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={handleBatchDelete}
              disabled={batchDeleteMutation.isPending}
            >
              {batchDeleteMutation.isPending ? 'Deleting...' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogPopup>
      </Dialog>
      {confirmDialog}
    </div>
  )
}
