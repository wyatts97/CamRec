import { motion } from 'framer-motion'
import { Play, Heart, Download, Loader2, Wrench } from 'lucide-react'
import { Avatar, AvatarImage, AvatarFallback } from '@/components/selia/avatar'
import { Button } from '@/components/selia/button'
import { Checkbox } from '@/components/selia/checkbox'
import { cn, formatBytes } from '@/lib/utils'
import { useDateFormat } from '@/lib/timezone-context'
import { api, type Recording } from '@/lib/api'
import { Timestamp } from '@/components/ui/timestamp'
import { useSpriteScrub } from '@/hooks/useSpriteScrub'
import { ScrubOverlay } from '@/components/ui/scrub-overlay'

interface RecordingVideoCardProps {
  recording: Recording
  /** Omit on browse-only surfaces (dashboard rail) to hide the button. */
  onFavorite?: (e: React.MouseEvent) => void
  onDownload?: (e: React.MouseEvent) => void
  onRepair?: (e: React.MouseEvent) => void
  isRepairing?: boolean
  onClick: () => void
  selected?: boolean
  onSelect?: (e: React.MouseEvent) => void
}

export function RecordingVideoCard({
  recording,
  onFavorite,
  onDownload,
  onRepair,
  isRepairing,
  onClick,
  selected,
  onSelect,
}: RecordingVideoCardProps) {
  const fmt = useDateFormat()
  const scrub = useSpriteScrub(
    recording.sprite_ready ? api.recordings.getSpriteVttUrl(recording.id) : null,
  )

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="w-full"
    >
      <div
        className="group relative overflow-hidden rounded-2xl border border-border/50 bg-card/30 backdrop-blur-md transition-all duration-300 hover:border-primary/50 hover:shadow-xl hover:shadow-primary/10 cursor-pointer"
        onClick={onClick}
      >
        {/* Thumbnail */}
        <div className="relative aspect-video overflow-hidden bg-secondary" {...scrub.handlers}>
          <ScrubOverlay style={scrub.style} fraction={scrub.fraction} />
          {onSelect && (
            <div
              className="absolute top-2 left-2 z-10"
              onClick={(e) => e.stopPropagation()}
            >
              <Checkbox
                checked={selected}
                onClick={onSelect}
                aria-label={`Select recording ${recording.id}`}
              />
            </div>
          )}
          {recording.thumbnail_ready ? (
            <>
              <motion.img
                src={api.recordings.getThumbnailUrl(
                  recording.id,
                  recording.file_size ?? recording.created_at,
                )}
                alt={`${recording.username} recording`}
                className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-110"
                loading="lazy"
                decoding="async"
                onError={(e) => {
                  const img = e.target as HTMLImageElement
                  img.style.display = 'none'
                }}
              />

              {/* Gradient overlay */}
              <div className="absolute inset-0 bg-gradient-to-t from-background/80 to-transparent opacity-60 transition-opacity duration-300 group-hover:opacity-40" />

              {/* Duration badge — bottom-right */}
              {recording.duration_seconds != null && recording.status !== 'processing' && (
                <div className="absolute bottom-2 right-2">
                  <Timestamp seconds={recording.duration_seconds} />
                </div>
              )}

              {/* Processing badge — top-right */}
              {recording.status === 'processing' && (
                <div className="absolute top-2 right-2 z-10 flex items-center gap-1.5 rounded-full bg-primary/90 px-2.5 py-1 text-xs font-medium text-primary-foreground shadow-sm">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Processing
                </div>
              )}

              {/* Play hover overlay */}
              <div className="absolute inset-0 flex items-center justify-center bg-background/20 backdrop-blur-[2px] opacity-0 transition-opacity duration-300 group-hover:opacity-100">
                <motion.div
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  className="flex h-14 w-14 items-center justify-center rounded-full bg-background/90 shadow-lg shadow-primary/20"
                >
                  <Play className="h-6 w-6 text-primary-ink ml-0.5" />
                </motion.div>
              </div>
            </>
          ) : (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-secondary">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground mb-2" />
              <span className="text-xs text-muted-foreground font-medium">Processing…</span>
            </div>
          )}
        </div>

        {/* Content */}
        <div className="flex flex-col gap-3 p-4">
          <div className="flex items-center justify-between gap-2">
            {/* Author */}
            <div className="flex items-center gap-2 min-w-0">
              <Avatar size="sm">
                <AvatarImage
                  src={api.users.getAvatarUrl(recording.user_id)}
                  alt={recording.username}
                />
                <AvatarFallback className="text-xs">
                  {recording.username[0].toUpperCase()}
                </AvatarFallback>
              </Avatar>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-foreground truncate">
                  @{recording.username}
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {fmt(recording.ended_at || recording.created_at)}
                </p>
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-0.5 shrink-0">
              {onFavorite && (
                <Button
                  variant="plain"
                  size="icon"
                  className="h-8 w-8"
                  onClick={onFavorite}
                  title={recording.is_favorite ? 'Unfavorite' : 'Favorite'}
                >
                  <Heart
                    className={cn(
                      'h-4 w-4',
                      recording.is_favorite && 'fill-danger text-danger',
                    )}
                  />
                </Button>
              )}
              {recording.status !== 'processing' && (recording.status === 'failed' || recording.is_corrupt) && onRepair && (
                <Button
                  variant="plain"
                  size="icon"
                  className="h-8 w-8 text-warning hover:text-warning/80"
                  onClick={onRepair}
                  disabled={isRepairing}
                  title="Repair recording"
                >
                  {isRepairing ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Wrench className="h-4 w-4" />
                  )}
                </Button>
              )}
              {onDownload && (
                <Button
                  variant="plain"
                  size="icon"
                  className="h-8 w-8"
                  onClick={onDownload}
                  title="Download"
                >
                  <Download className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>

          {recording.file_size != null && (
            <p className="text-xs text-muted-foreground">
              {formatBytes(recording.file_size)}
            </p>
          )}
        </div>
      </div>
    </motion.div>
  )
}
