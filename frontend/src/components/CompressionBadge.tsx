import { Badge } from '@/components/selia/badge'
import type { Recording } from '@/lib/api'
import { formatBytes } from '@/lib/utils'

/** Compact post-recording compression state for a recording. */
export default function CompressionBadge({ recording, className }: { recording: Recording; className?: string }) {
  const { compress_status: status, original_size: original, file_size: size } = recording
  switch (status) {
    case 'pending':
      return <Badge variant="secondary" size="sm" className={className}>Queued for AV1</Badge>
    case 'processing':
      return <Badge variant="info" size="sm" className={className}>Compressing…</Badge>
    case 'done': {
      const saved = original && size ? Math.round((1 - size / original) * 100) : null
      return (
        <Badge
          variant="success"
          size="sm"
          className={className}
          title={original ? `Original capture was ${formatBytes(original)}` : undefined}
        >
          AV1{saved != null && saved > 0 ? ` · −${saved}%` : ''}
        </Badge>
      )
    }
    case 'skipped':
      return (
        <Badge variant="secondary" size="sm" className={className} title={recording.compress_error ?? undefined}>
          Original kept
        </Badge>
      )
    case 'failed':
      return (
        <Badge variant="warning" size="sm" className={className} title={recording.compress_error ?? undefined}>
          Not compressed
        </Badge>
      )
    default:
      return null
  }
}
