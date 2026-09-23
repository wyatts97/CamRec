import { type LucideIcon } from 'lucide-react'
import { Button } from 'components/selia/button'

interface EmptyStateProps {
  icon: LucideIcon
  title: string
  description: string
  actionLabel?: string
  onAction?: () => void
}

export default function EmptyState({ icon: Icon, title, description, actionLabel, onAction }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="flex flex-col items-center gap-4 p-6 sm:p-8 rounded-2xl bg-card border border-border shadow-subtle max-w-sm">
        <div className="flex items-center justify-center h-16 w-16 rounded-full bg-primary-subtle">
          <Icon className="h-8 w-8 text-primary-ink" />
        </div>
        <div>
          <p className="text-lg font-medium text-foreground">{title}</p>
          <p className="text-muted-foreground mt-1 text-sm">{description}</p>
        </div>
        {actionLabel && onAction && (
          <Button onClick={onAction}>
            {actionLabel}
          </Button>
        )}
      </div>
    </div>
  )
}
