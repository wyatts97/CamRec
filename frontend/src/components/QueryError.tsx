import { AlertCircle, RefreshCw } from 'lucide-react'
import { Button } from '@/components/selia/button'

interface QueryErrorProps {
  /** The error thrown by the query, if available. */
  error?: unknown
  /** What failed, in the user's terms: "recordings", "storage stats". */
  what?: string
  onRetry?: () => void
}

/**
 * Rendered in place of a page's content when its query fails.
 *
 * Pages previously rendered only their empty state on error, so an unreachable
 * API looked identical to an empty library -- "No recordings yet" when the
 * backend was simply down.
 */
export default function QueryError({ error, what = 'this page', onRetry }: QueryErrorProps) {
  const message = error instanceof Error ? error.message : null

  return (
    <div className="flex flex-col items-center justify-center py-16 text-center" role="alert">
      <div className="flex flex-col items-center gap-4 p-6 sm:p-8 rounded-2xl bg-card border border-border shadow-subtle max-w-sm">
        <div className="flex items-center justify-center h-16 w-16 rounded-full bg-danger/10">
          <AlertCircle className="h-8 w-8 text-danger" aria-hidden="true" />
        </div>
        <div>
          <p className="text-lg font-medium text-foreground">Couldn&apos;t load {what}</p>
          <p className="text-muted-foreground mt-1 text-sm">
            {message ?? 'The server did not respond. It may be restarting.'}
          </p>
        </div>
        {onRetry && (
          <Button variant="secondary" onClick={onRetry}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            Try again
          </Button>
        )}
      </div>
    </div>
  )
}
