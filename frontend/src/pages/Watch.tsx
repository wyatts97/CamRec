import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import { Tv, Search, Trash2, Download, X, ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/selia/button'
import { Input } from '@/components/selia/input'
import { Select, SelectTrigger, SelectValue, SelectPopup, SelectList, SelectItem } from '@/components/selia/select'
import { Pagination, PaginationList, PaginationItem, PaginationButton } from '@/components/selia/pagination'
import EmptyState from '@/components/EmptyState'
import QueryError from '@/components/QueryError'
import { VideoGridSkeleton } from '@/components/Skeleton'
import { StaggerContainer, StaggerItem } from '@/components/motion'
import { RecordingVideoCard } from '@/components/ui/recording-video-card'
import { useConfirm } from '@/components/ConfirmDialog'
import { api, type Recording } from '@/lib/api'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import toast from 'react-hot-toast'
import { downloadFiles } from '@/lib/utils'

// ~2 minutes at 5s. Thumbnails that aren't ready by then are not coming.
const THUMBNAIL_POLL_MAX_ATTEMPTS = 24

const ITEMS_PER_PAGE = 12

// Frontend sort labels map onto the backend's (sort_by, sort_order) vocabulary.
// "favorites" is handled specially server-side (floats favorites to the top
// without excluding non-favorites), so it needs no sort_order.
const SORT_MAP: Record<string, { sortBy: string; sortOrder?: string }> = {
  newest: { sortBy: 'date', sortOrder: 'desc' },
  oldest: { sortBy: 'date', sortOrder: 'asc' },
  longest: { sortBy: 'duration', sortOrder: 'desc' },
  shortest: { sortBy: 'duration', sortOrder: 'asc' },
  largest: { sortBy: 'size', sortOrder: 'desc' },
  favorites: { sortBy: 'favorites' },
}

function getPageNumbers(page: number, totalPages: number): (number | 'ellipsis')[] {
  const pages: (number | 'ellipsis')[] = []
  const add = (p: number) => pages.push(p)
  const window = 1
  add(1)
  if (page - window > 2) pages.push('ellipsis')
  for (let p = Math.max(2, page - window); p <= Math.min(totalPages - 1, page + window); p++) add(p)
  if (page + window < totalPages - 1) pages.push('ellipsis')
  if (totalPages > 1) add(totalPages)
  return pages
}

export default function Watch() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchQuery, setSearchQuery] = useState('')
  const [sortBy, setSortBy] = useState('newest')
  const [page, setPage] = useState(1)

  const debouncedSearch = useDebouncedValue(searchQuery.trim(), 300)

  const [repairingId, setRepairingId] = useState<number | null>(null)
  const { confirm, confirmDialog } = useConfirm()
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  const toggleSelection = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const clearSelection = () => setSelectedIds(new Set())

  const batchDeleteMutation = useMutation({
    mutationFn: (ids: number[]) => api.recordings.batchDelete(ids),
    onSuccess: (res) => {
      toast.success(`${res.deleted} recording${res.deleted !== 1 ? 's' : ''} deleted`)
      clearSelection()
      queryClient.invalidateQueries({ queryKey: ['recordings', 'watch'] })
    },
    onError: (err: any) => {
      toast.error(err.message || 'Batch delete failed')
    },
  })

  // Selected items download as individual files, one after another.
  const [isDownloading, setIsDownloading] = useState(false)
  const handleBatchDownload = async (ids: number[]) => {
    setIsDownloading(true)
    try {
      await downloadFiles(ids.map((id) => api.recordings.getDownloadUrl(id)))
    } finally {
      setIsDownloading(false)
    }
  }

  const queryKey = ['recordings', 'watch', page, sortBy, debouncedSearch] as const

  const toggleFavoriteMutation = useMutation({
    mutationFn: (id: number) => api.recordings.toggleFavorite(id),
    // Optimistic update: flip the flag instantly, roll back on error.
    onMutate: async (id: number) => {
      await queryClient.cancelQueries({ queryKey })
      const previous = queryClient.getQueryData(queryKey)
      queryClient.setQueryData(queryKey, (old: any) => {
        if (!old) return old
        return {
          ...old,
          recordings: old.recordings.map((r: Recording) =>
            r.id === id ? { ...r, is_favorite: !r.is_favorite } : r
          ),
        }
      })
      return { previous }
    },
    onError: (_err, _id, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKey, context.previous)
      }
      toast.error('Failed to update favorite')
    },
  })

  const handleRepair = async (id: number) => {
    setRepairingId(id)
    try {
      const updated = await api.recordings.repair(id)
      queryClient.setQueryData(queryKey, (old: any) => {
        if (!old) return old
        return {
          ...old,
          recordings: old.recordings.map((r: Recording) =>
            r.id === updated.id ? updated : r
          ),
        }
      })
      toast.success('Recording repaired successfully')
    } catch (err: any) {
      toast.error(err.message || 'Repair failed')
    } finally {
      setRepairingId(null)
    }
  }

  const { data, isLoading, isFetching, isError, error, refetch } = useQuery({
    queryKey,
    queryFn: () =>
      api.recordings.list(page, ITEMS_PER_PAGE, 'completed,stopped,failed', undefined, {
        ...SORT_MAP[sortBy],
        usernameFilter: debouncedSearch || undefined,
      }),
    placeholderData: keepPreviousData,
    refetchInterval: (query) => {
      const recs = query.state.data?.recordings ?? []
      if (!recs.some((r) => !r.thumbnail_ready)) return false
      // Bounded: a failed recording never gets a thumbnail, so one bad row
      // used to pin a 5s poll for as long as the tab stayed open.
      if (query.state.dataUpdateCount > THUMBNAIL_POLL_MAX_ATTEMPTS) return false
      return 5000
    },
  })

  const recordings = useMemo(() => data?.recordings || [], [data])
  const total = data?.total || 0
  const totalPages = Math.max(1, Math.ceil(total / ITEMS_PER_PAGE))

  // Reset to page 1 when filters change
  const handleSearch = (val: string) => {
    setSearchQuery(val)
    setPage(1)
  }
  const handleSort = (value: unknown) => {
    const val = String(value)
    setSortBy(val)
    setPage(1)
  }

  const handleDeleteSelected = async () => {
    const ok = await confirm({
      title: `Delete ${selectedIds.size} recording(s)?`,
      description: 'The recordings and their files will be permanently deleted. This cannot be undone.',
      confirmLabel: 'Delete',
    })
    if (ok) batchDeleteMutation.mutate(Array.from(selectedIds))
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-foreground tracking-tight">Watch</h1>
        <p className="text-muted-foreground mt-1">
          Browse and play your completed, stopped, and failed recordings
        </p>
      </div>

      {/* Filters bar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search by username…"
            value={searchQuery}
            onChange={(e) => handleSearch(e.target.value)}
            className="pl-9 h-9 text-sm"
          />
        </div>
        <Select value={sortBy} onValueChange={handleSort}>
          <SelectTrigger className="h-9 w-32 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectPopup>
            <SelectList>
              <SelectItem value="newest">Newest</SelectItem>
              <SelectItem value="oldest">Oldest</SelectItem>
              <SelectItem value="longest">Longest</SelectItem>
              <SelectItem value="shortest">Shortest</SelectItem>
              <SelectItem value="largest">Largest</SelectItem>
              <SelectItem value="favorites">Favorites</SelectItem>
            </SelectList>
          </SelectPopup>
        </Select>
        <span className="text-xs text-muted-foreground">
          {total} recording{total !== 1 ? 's' : ''}
        </span>
      </div>

      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 p-3 rounded-lg bg-secondary border border-border/50">
          <span className="text-sm font-medium">
            {selectedIds.size} selected
          </span>
          <div className="flex-1" />
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleBatchDownload(Array.from(selectedIds))}
            disabled={isDownloading}
          >
            <Download className="h-3.5 w-3.5 mr-1.5" />
            Download Selected
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={handleDeleteSelected}
            disabled={batchDeleteMutation.isPending}
          >
            <Trash2 className="h-3.5 w-3.5 mr-1.5" />
            Delete Selected
          </Button>
          <Button variant="plain" size="sm" onClick={clearSelection}>
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}

      {isError ? (
        <QueryError error={error} what="recordings" onRetry={() => refetch()} />
      ) : isLoading ? (
        <VideoGridSkeleton count={8} />
      ) : recordings.length === 0 ? (
        <EmptyState
          icon={Tv}
          title={searchQuery ? 'No matching recordings' : 'No recordings yet'}
          description={searchQuery ? 'Try a different search' : 'Start a recording and come back here when it finishes.'}
        />
      ) : (
        <>
          <StaggerContainer
            className={`grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 transition-opacity ${isFetching ? 'opacity-60' : ''}`}
          >
            {recordings.map((recording) => (
              <StaggerItem key={recording.id}>
              <RecordingVideoCard
                recording={recording}
                onClick={() => navigate(`/watch/${recording.id}`)}
                onFavorite={(e) => {
                  e.stopPropagation()
                  toggleFavoriteMutation.mutate(recording.id)
                }}
                onDownload={(e) => {
                  e.stopPropagation()
                  const a = document.createElement('a')
                  a.href = api.recordings.getDownloadUrl(recording.id)
                  a.download = ''
                  document.body.appendChild(a)
                  a.click()
                  document.body.removeChild(a)
                }}
                isRepairing={repairingId === recording.id}
                onRepair={(e) => {
                  e.stopPropagation()
                  if (repairingId === recording.id) return
                  handleRepair(recording.id)
                }}
                selected={selectedIds.has(recording.id)}
                onSelect={(e) => {
                  e.stopPropagation()
                  toggleSelection(recording.id)
                }}
              />
              </StaggerItem>
            ))}
          </StaggerContainer>

          {/* Pagination */}
          {totalPages > 1 && (
            <Pagination className="pt-4">
              <PaginationList>
                <PaginationItem>
                  <PaginationButton
                    disabled={page === 1}
                    onClick={() => page > 1 && setPage((p) => p - 1)}
                    aria-label="Previous page"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </PaginationButton>
                </PaginationItem>
                {getPageNumbers(page, totalPages).map((p, i) =>
                  p === 'ellipsis' ? (
                    <PaginationItem key={`ellipsis-${i}`}>
                      <span className="px-2 text-sm text-muted-foreground">…</span>
                    </PaginationItem>
                  ) : (
                    <PaginationItem key={p}>
                      <PaginationButton active={p === page} onClick={() => setPage(p)}>
                        {p}
                      </PaginationButton>
                    </PaginationItem>
                  )
                )}
                <PaginationItem>
                  <PaginationButton
                    disabled={page === totalPages}
                    onClick={() => page < totalPages && setPage((p) => p + 1)}
                    aria-label="Next page"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </PaginationButton>
                </PaginationItem>
              </PaginationList>
            </Pagination>
          )}
        </>
      )}
      {confirmDialog}
    </div>
  )
}
