import { useState, useCallback, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { tabListKeyDown, tabProps, tabPanelProps } from '@/lib/a11y'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, LoaderCircle, Radio, Square, Tv, Calendar, Clock, MessageCircle, Scissors } from 'lucide-react'
import { Button } from '@/components/selia/button'
import { IconBox } from '@/components/selia/icon-box'
import { api } from '@/lib/api'
import { formatDuration } from '@/lib/utils'
import { useDateFormat } from '@/lib/timezone-context'
import ChatPanel from '@/components/ChatPanel'
import ChatStatusBadge from '@/components/ChatStatusBadge'
import { useConfirm } from '@/components/ConfirmDialog'
import FlvPlayer from '@/components/FlvPlayer'
import ErrorBoundary from '@/components/ErrorBoundary'
import toast from 'react-hot-toast'

const LIVE_TABS = ['player', 'chat'] as const

export default function LivePlayer() {
  const fmt = useDateFormat()
  const { confirm, confirmDialog } = useConfirm()
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const recordingId = Number(id)
  const [chatSearch, setChatSearch] = useState('')
  const [showChat, setShowChat] = useState(false)
  const [liveUrl, setLiveUrl] = useState<string | null>(null)
  const [streamType, setStreamType] = useState<'hls' | 'flv' | 'rtmp'>('flv')
  const [urlError, setUrlError] = useState(false)
  const [playerError, setPlayerError] = useState(false)
  const { data: recording, isLoading } = useQuery({
    queryKey: ['recording', recordingId],
    queryFn: () => api.recordings.get(recordingId),
    enabled: !isNaN(recordingId),
    // Once the stream ends this row stops changing (and later carries the
    // full transcript), so stop polling it.
    refetchInterval: (q: any) => {
      const status = q.state.data?.status
      return status === undefined || status === 'pending' || status === 'recording' ? 5000 : false
    },
  })

  const fetchLiveUrl = useCallback(async () => {
    if (isNaN(recordingId)) return
    try {
      setUrlError(false)
      const { live_url, type } = await api.recordings.getLiveUrl(recordingId)
      setLiveUrl(live_url)
      setStreamType(type)
      setPlayerError(false)
    } catch (e: any) {
      setUrlError(true)
      toast.error(e?.message || 'Stream URL unavailable')
    }
  }, [recordingId])

  const streamIsActive = recording?.status === 'pending' || recording?.status === 'recording'

  // Chat capture state lives on the active-recordings feed (shared cache with
  // Layout/Live), not on the recording row.
  const { data: activeRecordings } = useQuery({
    queryKey: ['activeRecordings'],
    queryFn: () => api.recordings.getActive(),
    enabled: streamIsActive,
    refetchInterval: 10000,
  })
  const activeEntry = activeRecordings?.find((r) => r.id === recordingId)

  useEffect(() => {
    // Once the stream has ended there is no URL to get, so continuing to poll
    // only produced a 404 and an error toast every 30 seconds, forever.
    if (!streamIsActive) return
    fetchLiveUrl()
    const interval = setInterval(fetchLiveUrl, 30000)
    return () => clearInterval(interval)
  }, [fetchLiveUrl, streamIsActive])

  // When the player reports an error, immediately refresh the URL. TikTok live
  // URLs expire after ~5 minutes, so a fresh URL often fixes playback.
  useEffect(() => {
    if (!playerError) return
    const timeout = setTimeout(() => {
      fetchLiveUrl()
    }, 500)
    return () => clearTimeout(timeout)
  }, [playerError, fetchLiveUrl])

  const stopMutation = useMutation({
    mutationFn: () => api.recordings.stop(recordingId),
    onSuccess: () => {
      toast.success('Recording stopped')
      queryClient.invalidateQueries({ queryKey: ['recordings'] })
      queryClient.invalidateQueries({ queryKey: ['activeRecordings'] })
      queryClient.invalidateQueries({ queryKey: ['recording', recordingId] })
    },
    onError: () => {
      toast.error('Failed to stop recording')
    },
  })

  const recordingActive = recording?.status === 'pending' || recording?.status === 'recording'

  const { data: clipStatus } = useQuery({
    queryKey: ['liveClip', recordingId],
    queryFn: () => api.recordings.liveClipStatus(recordingId),
    enabled: !isNaN(recordingId) && !!recordingActive,
    refetchInterval: (q: any) => (q.state.data?.active ? 1000 : false),
  })
  const clipActive = clipStatus?.active ?? false
  const clipElapsed = clipStatus?.elapsed ?? 0

  const startClipMutation = useMutation({
    mutationFn: () => api.recordings.liveClipStart(recordingId),
    onSuccess: () => {
      toast.success('Clip started — recording the live moment')
      queryClient.invalidateQueries({ queryKey: ['liveClip', recordingId] })
    },
    onError: (e: Error) => toast.error(e.message || 'Failed to start clip'),
  })

  const stopClipMutation = useMutation({
    mutationFn: () => api.recordings.liveClipStop(recordingId),
    onSuccess: (res) => {
      toast.success('Clip saved')
      queryClient.invalidateQueries({ queryKey: ['liveClip', recordingId] })
      queryClient.invalidateQueries({ queryKey: ['clips'] })
      if (res.clip_id) {
        toast('View it in Clips', { icon: '🎬' })
      }
    },
    onError: (e: Error) => toast.error(e.message || 'Failed to save clip'),
  })

  const handleStop = async () => {
    const ok = await confirm({
      title: 'Stop this recording?',
      description: 'The live capture ends immediately. Footage recorded so far is kept, but capture cannot be resumed.',
      confirmLabel: 'Stop Recording',
    })
    if (ok) stopMutation.mutate()
  }

  if (isLoading) {
    return (
      <div
        className="flex items-center justify-center py-12"
        role="status"
        aria-label="Loading"
      >
        <LoaderCircle className="h-6 w-6 animate-spin motion-reduce:animate-none text-primary-ink" aria-hidden="true" />
        <span className="sr-only">Loading…</span>
      </div>
    )
  }

  if (!recording) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <p className="text-lg font-medium text-foreground">Recording not found</p>
        <Button className="mt-4" onClick={() => navigate('/live')}>
          Back to Live
        </Button>
      </div>
    )
  }

  const isActive = recording.status === 'pending' || recording.status === 'recording'
  const elapsed = recording.duration_seconds
    ? formatDuration(recording.duration_seconds)
    : '--:--'

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Button variant="plain" size="icon" onClick={() => navigate('/live')}>
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div className="flex-1 min-w-0">
          <h1 className="text-xl font-bold text-foreground tracking-tight truncate">
            @{recording.username}
          </h1>
          <p className="text-xs text-muted-foreground flex items-center gap-1">
            {isActive && (
              <>
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-danger opacity-75" />
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-danger" />
                </span>
                <span className="text-danger font-medium">LIVE</span>
                <span className="mx-1">·</span>
              </>
            )}
            <span>Recording #{recording.id}</span>
          </p>
        </div>
        {isActive && (
          <Button
            variant={clipActive ? 'danger' : 'secondary'}
            size="sm"
            onClick={() => (clipActive ? stopClipMutation.mutate() : startClipMutation.mutate())}
            disabled={startClipMutation.isPending || stopClipMutation.isPending}
            className="shrink-0"
            title={clipActive ? 'Stop and save this clip' : 'Start clipping from the live stream'}
          >
            <Scissors className="h-3.5 w-3.5 mr-1.5" />
            {clipActive ? `Stop Clip · ${formatDuration(clipElapsed)}` : 'Start Clip'}
          </Button>
        )}
        {isActive && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleStop}
            disabled={stopMutation.isPending}
            className="shrink-0"
          >
            <Square className="h-3.5 w-3.5 mr-1.5 fill-danger text-danger" />
            Stop
          </Button>
        )}
        <Button
          variant={showChat ? 'primary' : 'outline'}
          size="sm"
          className="hidden lg:inline-flex"
          onClick={() => setShowChat((s) => !s)}
        >
          <MessageCircle className="h-4 w-4" />
        </Button>
      </div>

      {/* Main layout */}
      <div className="flex gap-6">
        {/* Left column — player + metadata */}
        <div className="flex-1 min-w-0 space-y-6">
          <div className="relative rounded-xl overflow-hidden bg-black border border-border shadow-sm">
            {liveUrl && !urlError ? (
              <ErrorBoundary
                fallback={
                  <div className="w-full aspect-video flex flex-col items-center justify-center bg-gray-900">
                    <Tv className="h-10 w-10 text-gray-500 mb-3" />
                    <p className="text-gray-400 text-sm">Player crashed</p>
                    <Button variant="outline" size="sm" className="mt-3" onClick={fetchLiveUrl}>
                      Retry
                    </Button>
                  </div>
                }
              >
                <FlvPlayer
                  src={liveUrl}
                  type={streamType}
                  className="w-full aspect-video"
                  autoPlay
                  controls
                  onError={() => setPlayerError(true)}
                  onReady={() => setPlayerError(false)}
                />
              </ErrorBoundary>
            ) : (
              <div className="w-full aspect-video flex flex-col items-center justify-center bg-gray-900">
                {urlError ? (
                  <>
                    <Tv className="h-10 w-10 text-gray-500 mb-3" />
                    <p className="text-gray-400 text-sm">Stream unavailable</p>
                    <Button variant="outline" size="sm" className="mt-3" onClick={fetchLiveUrl}>
                      Retry
                    </Button>
                  </>
                ) : !isActive ? (
                  <>
                    <Radio className="h-10 w-10 text-gray-500 mb-3" />
                    <p className="text-gray-400 text-sm">This recording is no longer live</p>
                  </>
                ) : (
                  <>
                    <LoaderCircle className="h-10 w-10 text-gray-400 animate-spin mb-3" />
                    <p className="text-gray-400 text-sm">Loading stream…</p>
                  </>
                )}
              </div>
            )}
            {isActive && liveUrl && (
              <div className="absolute top-3 right-3 flex items-center gap-1.5 bg-black/70 text-white text-[10px] font-bold px-2 py-1 rounded-full uppercase">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-danger opacity-75" />
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-danger" />
                </span>
                {streamType}
              </div>
            )}
          </div>

          {/* Metadata cards */}
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="p-4 rounded-xl bg-card border border-border">
              <div className="flex items-center gap-2 mb-1">
                <IconBox variant="secondary-subtle" size="sm">
                  <Calendar className="h-3.5 w-3.5" />
                </IconBox>
                <p className="text-xs text-muted-foreground uppercase tracking-wider">Started</p>
              </div>
              <p className="mt-1 font-medium text-foreground">
                {recording.started_at ? fmt(recording.started_at) : '—'}
              </p>
            </div>
            <div className="p-4 rounded-xl bg-card border border-border">
              <div className="flex items-center gap-2 mb-1">
                <IconBox variant="secondary-subtle" size="sm">
                  <Clock className="h-3.5 w-3.5" />
                </IconBox>
                <p className="text-xs text-muted-foreground uppercase tracking-wider">Duration</p>
              </div>
              <p className="mt-1 font-medium text-foreground">{elapsed}</p>
            </div>
            <div className="p-4 rounded-xl bg-card border border-border">
              <div className="flex items-center gap-2 mb-1">
                <IconBox variant="secondary-subtle" size="sm">
                  <Radio className="h-3.5 w-3.5" />
                </IconBox>
                <p className="text-xs text-muted-foreground uppercase tracking-wider">Status</p>
              </div>
              <p className="mt-1 font-medium text-foreground capitalize">{recording.status}</p>
              {activeEntry && <ChatStatusBadge recording={activeEntry} className="mt-2" />}
            </div>
          </div>

          {/* Mobile chat */}
          <div className="lg:hidden border border-border rounded-xl overflow-hidden">
            <div
              className="flex border-b border-border bg-secondary"
              role="tablist"
              aria-label="Player views"
              onKeyDown={tabListKeyDown(
                LIVE_TABS,
                showChat ? 'chat' : 'player',
                (next) => setShowChat(next === 'chat'),
              )}
            >
              <button
                onClick={() => setShowChat(false)}
                {...tabProps('player', !showChat)}
                className={`px-4 py-2.5 text-sm font-medium transition-colors ${
                  !showChat
                    ? 'bg-background text-primary-ink border-b-2 border-primary -mb-px'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                Player
              </button>
              <button
                onClick={() => setShowChat(true)}
                {...tabProps('chat', showChat)}
                className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors ${
                  showChat
                    ? 'bg-background text-primary-ink border-b-2 border-primary -mb-px'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                <MessageCircle className="h-3.5 w-3.5" />
                Chat
              </button>
            </div>
            {showChat && (
              <div {...tabPanelProps('chat')}>
              <ChatPanel
                recording={recording}
                chatSearch={chatSearch}
                onChatSearchChange={setChatSearch}
                variant="inline"
              />
              </div>
            )}
          </div>
        </div>

        {/* Desktop sidebar chat */}
        {/* No wrapper: the "panel" variant already supplies its own border,
            width and background -- wrapping it nested two borders and left the
            two widths fighting. */}
        {showChat && (
          <ChatPanel
            recording={recording}
            chatSearch={chatSearch}
            onChatSearchChange={setChatSearch}
            variant="panel"
          />
        )}
      </div>
      {confirmDialog}
    </div>
  )
}
