import { X } from 'lucide-react'
import { type ExportJob } from '@/lib/api'
import { formatBytes } from '@/lib/utils'

interface ExportProgressProps {
  job: ExportJob
  onCancel: () => void
}

/** Inline progress bar for a running ZIP export. */
export default function ExportProgress({ job, onCancel }: ExportProgressProps) {
  const label =
    job.status === 'pending'
      ? 'Preparing export…'
      : `Compressing ${job.files_done} of ${job.total_files} files`

  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-subtle">
      <div className="flex items-center justify-between gap-4 mb-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground truncate">{label}</p>
          <p className="text-xs text-muted-foreground">
            {formatBytes(job.bytes_done)} of {formatBytes(job.total_bytes)}
          </p>
        </div>
        <button
          onClick={onCancel}
          aria-label="Cancel export"
          className="shrink-0 flex items-center justify-center h-8 w-8 rounded-lg text-muted-foreground hover:bg-accent transition-colors"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <div
        className="h-2 w-full rounded-full bg-secondary overflow-hidden"
        role="progressbar"
        aria-valuenow={Math.round(job.percent)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Export progress"
      >
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-300"
          style={{ width: `${job.percent}%` }}
        />
      </div>
    </div>
  )
}
