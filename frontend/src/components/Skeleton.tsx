import { cn } from '@/lib/utils'

/**
 * Base skeleton block. Animated shimmer that respects reduced-motion via the
 * `motion-reduce:animate-none` utility.
 */
export function Skeleton({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn(
        'animate-pulse motion-reduce:animate-none rounded-md bg-secondary',
        className,
      )}
      {...props}
    />
  )
}

/** Skeleton shaped like a video/recording card used in the Watch & Live grids. */
export function VideoCardSkeleton() {
  return (
    <div className="rounded-xl overflow-hidden bg-card border border-border shadow-sm">
      <Skeleton className="aspect-video rounded-none" />
      <div className="p-3 space-y-2">
        <div className="flex items-center gap-2">
          <Skeleton className="h-7 w-7 rounded-full" />
          <Skeleton className="h-4 w-28" />
        </div>
        <div className="flex items-center justify-between">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-3 w-12" />
        </div>
      </div>
    </div>
  )
}

/** A responsive grid of {@link VideoCardSkeleton}s. */
export function VideoGridSkeleton({
  count = 8,
  className,
}: {
  count?: number
  className?: string
}) {
  return (
    <div
      className={cn(
        'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6',
        className,
      )}
    >
      {Array.from({ length: count }).map((_, i) => (
        <VideoCardSkeleton key={i} />
      ))}
    </div>
  )
}

/** Skeleton row matching the list/table layout on Recordings & Watchlist. */
export function ListRowSkeleton() {
  return (
    <div className="flex items-center gap-3 px-3 py-3 border-b border-border/50 last:border-0">
      <Skeleton className="h-9 w-9 rounded-full shrink-0" />
      <div className="flex-1 space-y-1.5">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-3 w-24" />
      </div>
      <Skeleton className="h-8 w-20 rounded-md" />
    </div>
  )
}

/** A stack of {@link ListRowSkeleton}s. */
export function ListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="rounded-xl border border-border overflow-hidden">
      {Array.from({ length: rows }).map((_, i) => (
        <ListRowSkeleton key={i} />
      ))}
    </div>
  )
}
