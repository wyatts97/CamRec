import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Circle, Play, RefreshCw, Tv, X } from 'lucide-react'
import { Card, CardBody } from '@/components/selia/card'
import { Button } from '@/components/selia/button'
import { Badge } from '@/components/selia/badge'
import { Heading } from '@/components/selia/heading'
import { Text } from '@/components/selia/text'
import FlvPlayer from '@/components/FlvPlayer'
import { api, type ActiveRecording } from '@/lib/api'
import { cn, formatDuration } from '@/lib/utils'

export interface LiveProfileCardProps {
  userId: number
  username: string
  displayName?: string | null
  /** The in-progress recording for this user, if one is running. */
  recording?: ActiveRecording | null
  /** Starts a recording; shown as "Record" when there is no recording yet. */
  onRecord?: () => void
  recordPending?: boolean
  /** Live page: play the stream inside the card instead of linking away. */
  playable?: boolean
  /** Show the live room snapshot instead of the avatar (refreshed every minute). */
  screencap?: boolean
  onAvatarError?: () => void
  className?: string
}

/**
 * A live model as a photo card: the room snapshot (or avatar) fills the card,
 * with name, handle and the primary action over a gradient. Adapted from
 * Selia's profile block.
 */
export default function LiveProfileCard({
  userId,
  username,
  displayName,
  recording,
  onRecord,
  recordPending,
  playable = false,
  screencap = true,
  onAvatarError,
  className,
}: LiveProfileCardProps) {
  const [imageFailed, setImageFailed] = useState(false)
  const [screencapFailed, setScreencapFailed] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [bust, setBust] = useState(() => Math.floor(Date.now() / 60000))
  const name = displayName || username
  const useScreencap = screencap && !screencapFailed

  // Room snapshots change constantly; refresh once a minute.
  useEffect(() => {
    if (!useScreencap) return
    const t = setInterval(() => setBust(Math.floor(Date.now() / 60000)), 60000)
    return () => clearInterval(t)
  }, [useScreencap])

  return (
    <Card
      className={cn(
        'relative h-[420px] p-1 overflow-hidden group isolate',
        className,
      )}
    >
      {/* Background: the room snapshot or avatar, or a stream while playing */}
      {playing && recording ? (
        <InlineStream recordingId={recording.id} onClose={() => setPlaying(false)} />
      ) : imageFailed ? (
        <div
          className="absolute inset-0 rounded-xl bg-linear-to-br from-primary/40 via-avatar to-card flex items-center justify-center"
          aria-hidden="true"
        >
          <span className="text-7xl font-semibold text-foreground/70 select-none">
            {name[0]?.toUpperCase()}
          </span>
        </div>
      ) : (
        <img
          src={useScreencap ? api.users.getScreencapUrl(userId, bust) : api.users.getAvatarUrl(userId)}
          alt={`${name} (${username})`}
          className="absolute inset-0 size-full object-cover rounded-xl transition-transform duration-700 group-hover:scale-[1.03] motion-reduce:transition-none"
          loading="lazy"
          decoding="async"
          onError={() => {
            if (useScreencap) {
              setScreencapFailed(true)
              return
            }
            setImageFailed(true)
            onAvatarError?.()
          }}
        />
      )}

      {!playing && (
        <div className="bg-linear-to-b from-card/0 to-card absolute inset-x-0 bottom-0 h-3/4 rounded-[calc(var(--radius-xl)-3px)] pointer-events-none" />
      )}

      {/* Sits on the photo, not a theme surface: a fixed dark scrim keeps it
          legible over any image in every theme. */}
      <Badge pill size="sm" className="absolute top-3.5 left-3.5 z-10 font-semibold tracking-wide bg-black/60 text-white backdrop-blur-sm">
        <Circle className="fill-red-500 text-red-500" aria-hidden="true" />
        LIVE
      </Badge>

      {!playing && (
        <CardBody className="absolute bottom-0 inset-x-0 p-6 z-10">
          <Heading size="md" className="truncate">{name}</Heading>
          <Text className="text-muted truncate">{username}</Text>

          {recording && (
            <div className="flex flex-wrap items-center gap-2 mt-3">
              <Badge variant="secondary" size="sm" className="tabular-nums">
                REC {formatDuration(recording.duration_seconds)}
              </Badge>
            </div>
          )}

          <div className="flex items-center gap-2 mt-4">
            {recording ? (
              playable ? (
                <>
                  <Button variant="tertiary" size="lg" pill onClick={() => setPlaying(true)}>
                    <Play />
                    Watch here
                  </Button>
                  <Button
                    variant="plain"
                    size="lg"
                    pill
                    nativeButton={false}
                    render={<Link to={`/live/${recording.id}`} />}
                  >
                    Open
                  </Button>
                </>
              ) : (
                <Button
                  variant="tertiary"
                  size="lg"
                  pill
                  nativeButton={false}
                  render={<Link to={`/live/${recording.id}`} />}
                >
                  <Tv />
                  Watch Live
                </Button>
              )
            ) : (
              onRecord && (
                <Button
                  variant="tertiary"
                  size="lg"
                  pill
                  onClick={onRecord}
                  progress={recordPending}
                  disabled={recordPending}
                >
                  <Circle className="fill-danger text-danger" />
                  Record
                </Button>
              )
            )}
          </div>
        </CardBody>
      )}
    </Card>
  )
}

/** The live stream, playing inside the card (Live page). */
function InlineStream({ recordingId, onClose }: { recordingId: number; onClose: () => void }) {
  const [liveUrl, setLiveUrl] = useState<string | null>(null)
  const [streamType, setStreamType] = useState<'hls'>('hls')
  const [failed, setFailed] = useState(false)

  const fetchLiveUrl = useCallback(async () => {
    setFailed(false)
    try {
      const { live_url, type } = await api.recordings.getLiveUrl(recordingId)
      setLiveUrl(live_url)
      setStreamType(type)
    } catch {
      setFailed(true)
    }
  }, [recordingId])

  // Re-resolve periodically so a stream that moved CDN nodes recovers.
  useEffect(() => {
    fetchLiveUrl()
    const interval = setInterval(fetchLiveUrl, 30000)
    return () => clearInterval(interval)
  }, [fetchLiveUrl])

  return (
    <div className="absolute inset-0 rounded-xl overflow-hidden bg-black">
      {liveUrl && !failed ? (
        <FlvPlayer
          src={liveUrl}
          type={streamType}
          className="size-full"
          autoPlay
          muted
          controls={false}
          onError={() => setFailed(true)}
        />
      ) : (
        <div className="size-full flex flex-col items-center justify-center gap-3 text-white/70">
          {failed ? (
            <>
              <p className="text-sm">Stream unavailable</p>
              <Button variant="secondary" size="sm" onClick={fetchLiveUrl}>
                <RefreshCw />
                Retry
              </Button>
            </>
          ) : (
            <p className="text-sm">Loading stream…</p>
          )}
        </div>
      )}
      <Button
        variant="secondary"
        size="sm-icon"
        pill
        className="absolute top-3 right-3 z-10"
        onClick={onClose}
        aria-label="Stop watching"
      >
        <X />
      </Button>
    </div>
  )
}
