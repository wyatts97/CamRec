import { MessageCircle, MessageCircleOff } from 'lucide-react'
import { Badge } from '@/components/selia/badge'
import type { ActiveRecording } from '@/lib/api'

/**
 * Whether live chat is being captured for an active recording. Without this a
 * failed chat connection only showed up afterwards, as an empty chat timeline.
 */
export default function ChatStatusBadge({
  recording,
  className,
}: {
  recording: ActiveRecording
  className?: string
}) {
  if (recording.chat_connected) {
    return (
      <Badge variant="success" size="sm" className={className}>
        <MessageCircle aria-hidden="true" />
        Chat captured
      </Badge>
    )
  }
  const reason = recording.chat_error || 'Not connected'
  return (
    <Badge variant="warning" size="sm" className={className} title={reason}>
      <MessageCircleOff aria-hidden="true" />
      <span className="truncate max-w-[16rem]">Chat: {reason}</span>
    </Badge>
  )
}
