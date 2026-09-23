import { Play, Heart, Download, Loader2, Scissors } from 'lucide-react'
import { Card } from '@/components/selia/card'
import { Button } from '@/components/selia/button'
import { Checkbox } from '@/components/selia/checkbox'
import { cn, formatBytes, formatDuration } from '@/lib/utils'
import { useDateFormat } from '@/lib/timezone-context'
import { api, type Clip } from '@/lib/api'
import { useSpriteScrub } from '@/hooks/useSpriteScrub'
import { ScrubOverlay } from '@/components/ui/scrub-overlay'

interface ClipCardProps {
  clip: Clip
  onClick: () => void
  onFavorite?: (e: React.MouseEvent) => void
  onDownload?: (e: React.MouseEvent) => void
  /** Omit selection entirely (the player page has no bulk actions). */
  selected?: boolean
  onSelect?: (id: number) => void
  /** Show "@user · date" under the title. Off where the user is already known. */
  showUser?: boolean
}

/**
 * A clip in card form.
 *
 * Shared by the Clips grid and the Saved Clips grid on the player page, which
 * previously rendered clips as a cramped list of 64x40 thumbnails.
 */
export function ClipCard({
  clip,
  onClick,
  onFavorite,
  onDownload,
  selected,
  onSelect,
  showUser = true,
}: ClipCardProps) {
  const fmt = useDateFormat()
  const scrub = useSpriteScrub(clip.sprite_ready ? api.clips.getSpriteVttUrl(clip.id) : null)

  return (
    <Card
      className="group overflow-hidden cursor-pointer border border-border bg-card hover:shadow-md transition-shadow"
      onClick={onClick}
    >
      <div className="relative aspect-video bg-secondary overflow-hidden" {...scrub.handlers}>
        <ScrubOverlay style={scrub.style} fraction={scrub.fraction} />
        {onSelect && (
          <div className="absolute top-2 left-2 z-10" onClick={(e) => e.stopPropagation()}>
            <Checkbox
              checked={selected}
              onClick={(e) => {
                e.stopPropagation()
                onSelect(clip.id)
              }}
              aria-label={`Select clip ${clip.title || clip.id}`}
            />
          </div>
        )}

        {clip.thumbnail_ready ? (
          <img
            src={api.clips.getThumbnailUrl(clip.id, clip.file_size ?? clip.created_at)}
            alt={`${clip.username} clip thumbnail`}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
            loading="lazy"
            decoding="async"
            onError={(e) => {
              const img = e.target as HTMLImageElement
              img.style.display = 'none'
              const placeholder = img.nextElementSibling as HTMLElement
              if (placeholder) placeholder.style.display = 'flex'
            }}
          />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-secondary">
            <Loader2 className="h-8 w-8 text-muted-foreground animate-spin motion-reduce:animate-none mb-2" />
            <span className="text-xs text-muted-foreground font-medium">Processing…</span>
          </div>
        )}
        <div className="absolute inset-0 items-center justify-center bg-secondary hidden">
          <Scissors className="h-12 w-12 text-muted-foreground" aria-hidden="true" />
        </div>

        {clip.thumbnail_ready && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/30 opacity-0 group-hover:opacity-100 transition-opacity">
            <div className="h-12 w-12 rounded-full bg-background/90 flex items-center justify-center">
              <Play className="h-5 w-5 text-primary-ink ml-0.5" aria-hidden="true" />
            </div>
          </div>
        )}

        <div className="absolute bottom-2 right-2 bg-black/70 text-white text-xs px-1.5 py-0.5 rounded">
          {formatDuration(clip.duration_seconds)}
        </div>
      </div>

      <div className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="font-medium text-foreground truncate">
              {clip.title || `Clip from @${clip.username}`}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {showUser ? `@${clip.username} · ` : ''}
              {fmt(clip.created_at)}
            </p>
          </div>
          {(onFavorite || onDownload) && (
            <div className="flex items-center gap-1 shrink-0">
              {onFavorite && (
                <Button
                  variant="plain"
                  size="icon"
                  className="h-8 w-8"
                  onClick={onFavorite}
                  title={clip.is_favorite ? 'Unfavorite' : 'Favorite'}
                  aria-label={clip.is_favorite ? 'Remove from favorites' : 'Add to favorites'}
                >
                  <Heart className={cn('h-4 w-4', clip.is_favorite && 'fill-danger text-danger')} />
                </Button>
              )}
              {onDownload && (
                <Button
                  variant="plain"
                  size="icon"
                  className="h-8 w-8"
                  onClick={onDownload}
                  title="Download"
                  aria-label="Download clip"
                >
                  <Download className="h-4 w-4" />
                </Button>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
          <span>{formatDuration(clip.duration_seconds)}</span>
          <span>·</span>
          <span>{formatBytes(clip.file_size)}</span>
        </div>
      </div>
    </Card>
  )
}
