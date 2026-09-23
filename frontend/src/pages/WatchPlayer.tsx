import { useState, useRef, useCallback, useMemo, useEffect } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { tabListKeyDown, tabProps, tabPanelProps } from '@/lib/a11y'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { MediaPlayer, MediaProvider } from '@vidstack/react'
import { defaultLayoutIcons, DefaultVideoLayout } from '@vidstack/react/player/layouts/default'
import '@vidstack/react/player/styles/default/theme.css'
import '@vidstack/react/player/styles/default/layouts/video.css'
import { ArrowLeft, Download, Trash2, Loader2, FileText, MessageCircle, Calendar, Clock, HardDrive, FileVideo, Scissors, Film } from 'lucide-react'
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
import TranscriptPanel from '@/components/TranscriptPanel'
import ChatPanel from '@/components/ChatPanel'
import ClipDialog from '@/components/ClipDialog'
import { ClipCard } from '@/components/ui/clip-card'
import toast from 'react-hot-toast'

function downloadAsFile(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function triggerDownload(url: string) {
  const a = document.createElement('a')
  a.href = url
  a.download = ''
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

// Whisper gives us start times only, so a cue runs until the next one starts
// (capped, so a long gap doesn't leave one line on screen for minutes).
const SRT_MAX_CUE_SECONDS = 3

function srtTimestamp(totalSeconds: number): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  const hh = Math.floor(totalSeconds / 3600)
  const mm = Math.floor((totalSeconds % 3600) / 60)
  const ss = Math.floor(totalSeconds % 60)
  return `${pad(hh)}:${pad(mm)}:${pad(ss)},000`
}

function formatTranscriptAsSrt(transcriptText: string): string {
  const lines = transcriptText.split('\n').filter(Boolean)
  // Two passes: an entry's end time is the *next* entry's start, so nothing
  // can be emitted until the whole list is parsed.
  const parsed: { seconds: number; text: string }[] = []
  for (const line of lines) {
    const match = line.match(/\[(\d{2}:\d{2}(?::\d{2})?)\]\s*(.*)/)
    if (!match) continue
    const parts = match[1].split(':').map(Number)
    const seconds =
      parts.length === 3
        ? parts[0] * 3600 + parts[1] * 60 + parts[2]
        : parts[0] * 60 + parts[1]
    parsed.push({ seconds, text: match[2] })
  }

  return parsed
    .map((entry, i) => {
      const next = parsed[i + 1]
      let end = entry.seconds + SRT_MAX_CUE_SECONDS
      // Only clamp when the next cue is strictly later; two lines sharing a
      // timestamp would otherwise produce a zero-length cue that players drop.
      if (next && next.seconds > entry.seconds) end = Math.min(end, next.seconds)
      return `${i + 1}\n${srtTimestamp(entry.seconds)} --> ${srtTimestamp(end)}\n${entry.text}\n`
    })
    .join('\n')
}

function formatTranscriptAsTxt(transcriptText: string): string {
  return transcriptText
    .split('\n')
    .filter(Boolean)
    .map((line) => line.replace(/\[\d{2}:\d{2}(?::\d{2})?\]\s*/, ''))
    .join('\n')
}

// ~2 minutes at 5s.
const SPRITE_POLL_MAX_ATTEMPTS = 24

const WATCH_TABS = ['player', 'transcript', 'chat'] as const

export default function WatchPlayer() {
  const fmt = useDateFormat()
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const recordingId = Number(id)
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<'player' | 'transcript' | 'chat'>('player')
  const [showTranscript, setShowTranscript] = useState(false)
  const [showChat, setShowChat] = useState(false)
  const [transcriptSearch, setTranscriptSearch] = useState('')
  const [chatSearch, setChatSearch] = useState('')
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [clipDialogOpen, setClipDialogOpen] = useState(false)
  const [clipStartSeconds, setClipStartSeconds] = useState<number | null>(null)
  const playerRef = useRef<HTMLDivElement>(null)

  const { data: recording, isLoading } = useQuery({
    queryKey: ['recording', recordingId],
    queryFn: () => api.recordings.get(recordingId),
    enabled: !isNaN(recordingId),
    refetchInterval: (query: any) => {
      const rec = query.state.data
      if (!rec) return false
      // Whisper takes minutes on CPU; a 3s poll mostly re-fetched an unchanged row.
      if (rec.transcript_status === 'processing' || rec.transcript_status === 'pending') return 10000
      // Bounded: sprite generation can fail or be skipped entirely, in which
      // case this polled forever.
      if (!rec.sprite_ready && query.state.dataUpdateCount <= SPRITE_POLL_MAX_ATTEMPTS) return 5000
      return false
    },
  })

  const { data: clipsData } = useQuery({
    queryKey: ['clips', 'recording', recordingId],
    queryFn: () => api.clips.list(1, 100, 'date', 'desc', recordingId),
    enabled: !isNaN(recordingId) && recordingId > 0,
  })

  const recordingClips = clipsData?.clips || []

  const transcribeMutation = useMutation({
    mutationFn: () => api.recordings.transcribe(recordingId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['recording', recordingId] }),
  })

  const deleteMutation = useMutation({
    mutationFn: () => api.recordings.delete(recordingId),
    onSuccess: () => {
      toast.success('Recording deleted')
      queryClient.invalidateQueries({ queryKey: ['recordings'] })
      navigate('/watch')
    },
    onError: () => {
      toast.error('Failed to delete recording')
    },
  })

  const handleSeek = useCallback((seconds: number) => {
    const video = playerRef.current?.querySelector('video') as HTMLVideoElement | null
    if (video) video.currentTime = seconds
  }, [])

  // Capture where the user is in the recording, so the clip dialog can open
  // with Start Time already filled in.
  const openClipDialog = useCallback(() => {
    const video = playerRef.current?.querySelector('video') as HTMLVideoElement | null
    setClipStartSeconds(video && Number.isFinite(video.currentTime) ? video.currentTime : null)
    setClipDialogOpen(true)
  }, [])

  // Jump to timestamp from ?t= query parameter (e.g. from search results)
  useEffect(() => {
    const t = searchParams.get('t')
    if (!t || !recording) return
    const seconds = Number(t)
    if (isNaN(seconds) || seconds < 0) return

    let attempts = 0
    const maxAttempts = 30
    const interval = setInterval(() => {
      const video = playerRef.current?.querySelector('video') as HTMLVideoElement | null
      if (video && video.readyState >= 2) {
        video.currentTime = seconds
        clearInterval(interval)
        // Remove t from query string so refreshing won't re-seek
        const next = new URLSearchParams(searchParams)
        next.delete('t')
        setSearchParams(next, { replace: true })
        return
      }
      if (++attempts >= maxAttempts) clearInterval(interval)
    }, 200)

    return () => clearInterval(interval)
  }, [recording, searchParams, setSearchParams])

  const handleDownloadSrt = useCallback(() => {
    if (!recording?.transcript_text) return
    const srt = formatTranscriptAsSrt(recording.transcript_text)
    const baseName = recording.filename?.replace(/\.[^.]+$/, '') || `recording_${recording.id}`
    downloadAsFile(srt, `${baseName}.srt`, 'text/plain')
  }, [recording])

  const handleDownloadTxt = useCallback(() => {
    if (!recording?.transcript_text) return
    const txt = formatTranscriptAsTxt(recording.transcript_text)
    const baseName = recording.filename?.replace(/\.[^.]+$/, '') || `recording_${recording.id}`
    downloadAsFile(txt, `${baseName}.txt`, 'text/plain')
  }, [recording])

  const transcriptActions = useMemo(() => {
    if (!recording?.transcript_text || recording.transcript_status !== 'done') return null
    return (
      <div className="flex items-center gap-2 mt-2">
        <Button
          size="sm"
          variant="outline"
          onClick={handleDownloadSrt}
          className="text-xs"
        >
          <Download className="h-3 w-3" />
          Download SRT
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={handleDownloadTxt}
          className="text-xs"
        >
          <FileText className="h-3 w-3" />
          Download TXT
        </Button>
      </div>
    )
  }, [recording, handleDownloadSrt, handleDownloadTxt])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12" role="status" aria-label="Loading">
        <Loader2 className="h-6 w-6 text-primary-ink animate-spin motion-reduce:animate-none" />
        <span className="sr-only">Loading…</span>
      </div>
    )
  }

  if (!recording) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <p className="text-lg font-medium text-foreground">Recording not found</p>
        <Button className="mt-4" onClick={() => navigate('/watch')}>
          Back to Watch
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Button variant="plain" size="icon" onClick={() => navigate('/watch')}>
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <h1 className="text-2xl font-bold text-foreground tracking-tight truncate flex-1">
          @{recording.username}
        </h1>
        <Button
          variant={showTranscript ? "primary" : "outline"}
          size="sm"
          className="hidden lg:inline-flex"
          onClick={() => setShowTranscript((s) => !s)}
        >
          <FileText className="h-4 w-4" />
          Transcript
        </Button>
        <Button
          variant={showChat ? "primary" : "outline"}
          size="sm"
          className="hidden lg:inline-flex"
          onClick={() => setShowChat((s) => !s)}
        >
          <MessageCircle className="h-4 w-4" />
          Chat
        </Button>
      </div>

      {!recording.thumbnail_ready && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-warning/10 border border-warning/30">
          <Loader2 className="h-4 w-4 text-warning animate-spin shrink-0" />
          <p className="text-sm text-foreground font-medium">
            Video is still being processed. It will be available shortly.
          </p>
        </div>
      )}

      <div className="flex gap-6">
        {/* Left column */}
        <div className="flex-1 min-w-0 space-y-6">
          <div className="rounded-xl overflow-hidden bg-black border border-border shadow-sm" ref={playerRef}>
            {recording.thumbnail_ready ? (
              <MediaPlayer
                src={api.recordings.getStreamUrl(recording.id)}
                poster={api.recordings.getThumbnailUrl(
                  recording.id,
                  recording.file_size ?? recording.created_at,
                )}
                title={`@${recording.username}`}
                className="w-full aspect-video"
              >
                <MediaProvider />
                <DefaultVideoLayout
                  icons={defaultLayoutIcons}
                  thumbnails={recording.sprite_ready ? api.recordings.getSpriteVttUrl(recording.id) : undefined}
                />
              </MediaPlayer>
            ) : (
              <div className="w-full aspect-video flex flex-col items-center justify-center bg-gray-900">
                <Loader2 className="h-10 w-10 text-gray-400 animate-spin mb-3" />
                <p className="text-gray-400 text-sm">Processing video…</p>
              </div>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="p-4 rounded-xl bg-card border border-border">
              <div className="flex items-center gap-2 mb-1">
                <IconBox variant="secondary-subtle" size="sm">
                  <Calendar className="h-3.5 w-3.5" />
                </IconBox>
                <p className="text-xs text-muted-foreground uppercase tracking-wider">Recorded</p>
              </div>
              <p className="mt-1 font-medium text-foreground">
                {fmt(recording.ended_at || recording.created_at)}
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
                {formatDuration(recording.duration_seconds)}
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
                {formatBytes(recording.file_size)}
              </p>
            </div>
            <div className="p-4 rounded-xl bg-card border border-border">
              <div className="flex items-center gap-2 mb-1">
                <IconBox variant="secondary-subtle" size="sm">
                  <FileVideo className="h-3.5 w-3.5" />
                </IconBox>
                <p className="text-xs text-muted-foreground uppercase tracking-wider">Filename</p>
              </div>
              <p className="mt-1 font-medium text-foreground truncate" title={recording.filename}>
                {recording.filename}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => triggerDownload(api.recordings.getDownloadUrl(recording.id))}
            >
              <Download className="h-4 w-4" />
              Download
            </Button>
            <Button
              variant="outline"
              onClick={openClipDialog}
            >
              <Scissors className="h-4 w-4" />
              Clip
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

          {/* Saved Clips */}
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Film className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <h3 className="text-sm font-medium">Saved Clips</h3>
              <span className="text-xs text-muted-foreground ml-auto">
                {recordingClips.length} clip{recordingClips.length !== 1 ? 's' : ''}
              </span>
            </div>
            {recordingClips.length === 0 ? (
              <div className="rounded-xl border border-border bg-card px-4 py-6 text-center">
                <p className="text-sm text-muted-foreground">No clips yet</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Use the Clip button to extract segments from this recording.
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
                {recordingClips.map((clip) => (
                  <ClipCard
                    key={clip.id}
                    clip={clip}
                    // Every clip here belongs to the recording being watched,
                    // so repeating the username on each card is just noise.
                    showUser={false}
                    onClick={() => navigate(`/clips/${clip.id}`)}
                    onDownload={(e) => {
                      e.stopPropagation()
                      const a = document.createElement('a')
                      a.href = api.clips.getDownloadUrl(clip.id)
                      a.download = ''
                      document.body.appendChild(a)
                      a.click()
                      document.body.removeChild(a)
                    }}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Mobile transcript tab */}
          <div className="border border-border rounded-xl overflow-hidden lg:hidden">
            <div className="flex border-b border-border bg-secondary"
              role="tablist"
              aria-label="Player views"
              onKeyDown={tabListKeyDown(WATCH_TABS, activeTab, setActiveTab)}
            >
              <button
                onClick={() => setActiveTab('player')}
                {...tabProps('player', activeTab === 'player')}
                className={`px-4 py-2.5 text-sm font-medium transition-colors ${
                  activeTab === 'player'
                    ? 'bg-background text-primary-ink border-b-2 border-primary -mb-px'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                Player
              </button>
              <button
                onClick={() => setActiveTab('transcript')}
                {...tabProps('transcript', activeTab === 'transcript')}
                className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors ${
                  activeTab === 'transcript'
                    ? 'bg-background text-primary-ink border-b-2 border-primary -mb-px'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                <FileText className="h-3.5 w-3.5" />
                Transcript
                {recording.transcript_status === 'done' && (
                  <span className="ml-1 h-1.5 w-1.5 rounded-full bg-success" />
                )}
              </button>
              <button
                onClick={() => setActiveTab('chat')}
                {...tabProps('chat', activeTab === 'chat')}
                className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors ${
                  activeTab === 'chat'
                    ? 'bg-background text-primary-ink border-b-2 border-primary -mb-px'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                <MessageCircle className="h-3.5 w-3.5" />
                Chat
              </button>
            </div>

            {activeTab === 'transcript' && (
              <div {...tabPanelProps('transcript')}>
                <TranscriptPanel
                  recording={recording}
                  transcriptSearch={transcriptSearch}
                  onTranscriptSearchChange={setTranscriptSearch}
                  onTranscribe={() => transcribeMutation.mutate()}
                  isTranscribing={transcribeMutation.isPending}
                  onSeek={handleSeek}
                  variant="inline"
                />
                {transcriptActions}
              </div>
            )}
            {activeTab === 'chat' && (
              <div {...tabPanelProps('chat')}>
                <ChatPanel
                  recording={recording}
                  chatSearch={chatSearch}
                  onChatSearchChange={setChatSearch}
                  onSeek={handleSeek}
                  variant="inline"
                />
              </div>
            )}
          </div>
        </div>

        {/* Desktop sidebar panels */}
        {showTranscript && (
          <div className="hidden lg:flex lg:flex-col">
            <TranscriptPanel
              recording={recording}
              transcriptSearch={transcriptSearch}
              onTranscriptSearchChange={setTranscriptSearch}
              onTranscribe={() => transcribeMutation.mutate()}
              isTranscribing={transcribeMutation.isPending}
              onSeek={handleSeek}
              variant="panel"
            />
            {transcriptActions}
          </div>
        )}
        {/* The "panel" variant is already `hidden lg:flex` with its own width
            and border, so it needs no wrapper here. (The transcript panel above
            keeps one only because transcriptActions sits under it.) */}
        {showChat && (
          <ChatPanel
            recording={recording}
            chatSearch={chatSearch}
            onChatSearchChange={setChatSearch}
            onSeek={handleSeek}
            variant="panel"
          />
        )}
      </div>

      {recording && (
        <ClipDialog
          recording={recording}
          open={clipDialogOpen}
          onOpenChange={setClipDialogOpen}
          defaultStartSeconds={clipStartSeconds}
          onClipCreated={() => {
            queryClient.invalidateQueries({ queryKey: ['clips', 'recording', recordingId] })
          }}
        />
      )}

      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogPopup>
          <DialogHeader>
            <DialogTitle>Delete Recording?</DialogTitle>
            <DialogDescription>
              This action cannot be undone. The recording and its file will be permanently deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            <p className="text-sm text-muted-foreground">
              Are you sure you want to delete this recording?
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
