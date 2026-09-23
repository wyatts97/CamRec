import { useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { MediaPlayer, MediaProvider } from '@vidstack/react'
import { defaultLayoutIcons, DefaultVideoLayout } from '@vidstack/react/player/layouts/default'
import '@vidstack/react/player/styles/default/theme.css'
import '@vidstack/react/player/styles/default/layouts/video.css'
import { ArrowLeft, Download, Trash2, Loader2, Calendar, Clock, HardDrive, FileVideo } from 'lucide-react'
import { Button } from '@/components/selia/button'
import { IconBox } from '@/components/selia/icon-box'
import {
  Dialog,
  DialogPopup,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogBody,
  DialogFooter,
} from '@/components/selia/dialog'
import { api } from '@/lib/api'
import { formatBytes, formatDuration } from '@/lib/utils'
import { useDateFormat } from '@/lib/timezone-context'
import toast from 'react-hot-toast'

function triggerDownload(url: string) {
  const a = document.createElement('a')
  a.href = url
  a.download = ''
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

export default function ClipPlayer() {
  const fmt = useDateFormat()
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const clipId = Number(id)
  const queryClient = useQueryClient()
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const playerRef = useRef<HTMLDivElement>(null)

  const { data: clip, isLoading } = useQuery({
    queryKey: ['clip', clipId],
    queryFn: () => api.clips.get(clipId),
    enabled: !isNaN(clipId),
  })

  const deleteMutation = useMutation({
    mutationFn: () => api.clips.delete(clipId),
    onSuccess: () => {
      toast.success('Clip deleted')
      queryClient.invalidateQueries({ queryKey: ['clips'] })
      navigate('/clips')
    },
    onError: () => {
      toast.error('Failed to delete clip')
    },
  })

  if (isLoading) {
    return (
      <div
        className="flex items-center justify-center py-12"
        role="status"
        aria-label="Loading"
      >
        <Loader2 className="h-6 w-6 animate-spin motion-reduce:animate-none text-primary-ink" aria-hidden="true" />
        <span className="sr-only">Loading…</span>
      </div>
    )
  }

  if (!clip) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <p className="text-lg font-medium text-foreground">Clip not found</p>
        <Button className="mt-4" onClick={() => navigate('/clips')}>
          Back to Clips
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Button variant="plain" size="icon" onClick={() => navigate('/clips')}>
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <h1 className="text-2xl font-bold text-foreground tracking-tight truncate flex-1">
          {clip.title || `Clip from ${clip.username}`}
        </h1>
      </div>

      {!clip.thumbnail_ready && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-warning/10 border border-warning/30">
          <Loader2 className="h-4 w-4 text-warning animate-spin shrink-0" />
          <p className="text-sm text-foreground font-medium">
            Clip is still being processed. It will be available shortly.
          </p>
        </div>
      )}

      <div className="space-y-6">
        <div className="rounded-xl overflow-hidden bg-black border border-border shadow-sm" ref={playerRef}>
          {clip.thumbnail_ready ? (
            <MediaPlayer
              src={api.clips.getStreamUrl(clip.id)}
              poster={api.clips.getThumbnailUrl(
                clip.id,
                clip.file_size ?? clip.created_at,
              )}
              title={clip.title || `${clip.username} clip`}
              className="w-full aspect-video"
            >
              <MediaProvider />
              <DefaultVideoLayout
                icons={defaultLayoutIcons}
                thumbnails={clip.sprite_ready ? api.clips.getSpriteVttUrl(clip.id) : undefined}
              />
            </MediaPlayer>
          ) : (
            <div className="w-full aspect-video flex flex-col items-center justify-center bg-gray-900">
              <Loader2 className="h-10 w-10 text-gray-400 animate-spin mb-3" />
              <p className="text-gray-400 text-sm">Processing clip…</p>
            </div>
          )}
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="p-4 rounded-xl bg-card border border-border">
            <div className="flex items-center gap-2 mb-1">
              <IconBox variant="secondary-subtle" size="sm">
                <Calendar className="h-3.5 w-3.5" />
              </IconBox>
              <p className="text-xs text-muted-foreground uppercase tracking-wider">Created</p>
            </div>
            <p className="mt-1 font-medium text-foreground">
              {fmt(clip.created_at)}
            </p>
          </div>
          <div className="p-4 rounded-xl bg-card border border-border">
            <div className="flex items-center gap-2 mb-1">
              <IconBox variant="secondary-subtle" size="sm">
                <Clock className="h-3.5 w-3.5" />
              </IconBox>
              <p className="text-xs text-muted-foreground uppercase tracking-wider">Duration</p>
            </div>
            <p className="mt-1 font-medium text-foreground">
              {formatDuration(clip.duration_seconds)}
            </p>
          </div>
          <div className="p-4 rounded-xl bg-card border border-border">
            <div className="flex items-center gap-2 mb-1">
              <IconBox variant="secondary-subtle" size="sm">
                <HardDrive className="h-3.5 w-3.5" />
              </IconBox>
              <p className="text-xs text-muted-foreground uppercase tracking-wider">Size</p>
            </div>
            <p className="mt-1 font-medium text-foreground">
              {formatBytes(clip.file_size)}
            </p>
          </div>
          <div className="p-4 rounded-xl bg-card border border-border">
            <div className="flex items-center gap-2 mb-1">
              <IconBox variant="secondary-subtle" size="sm">
                <FileVideo className="h-3.5 w-3.5" />
              </IconBox>
              <p className="text-xs text-muted-foreground uppercase tracking-wider">Filename</p>
            </div>
            <p className="mt-1 font-medium text-foreground truncate" title={clip.filename}>
              {clip.filename}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap justify-end gap-2">
          <Button
            variant="outline"
            onClick={() => triggerDownload(api.clips.getDownloadUrl(clip.id))}
          >
            <Download className="h-4 w-4" />
            Download
          </Button>
          <Button
            variant="outline"
            onClick={() => setDeleteDialogOpen(true)}
            disabled={deleteMutation.isPending}
            className="ring-danger/40 text-danger hover:bg-danger/10"
          >
            <Trash2 className="h-4 w-4" />
            Delete
          </Button>
        </div>
      </div>

      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogPopup>
          <DialogHeader>
            <DialogTitle>Delete Clip?</DialogTitle>
            <DialogDescription>
              This action cannot be undone. The clip file will be permanently deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            <p className="text-sm text-muted-foreground">
              Are you sure you want to delete this clip?
            </p>
          </DialogBody>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                deleteMutation.mutate()
                setDeleteDialogOpen(false)
              }}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogPopup>
      </Dialog>
    </div>
  )
}
