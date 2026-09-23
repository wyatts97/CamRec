import React, { useRef } from 'react'
import { FileText, Loader2, Search } from 'lucide-react'
import { Button } from 'components/selia/button'
import { Input } from 'components/selia/input'
import type { Recording } from '@/lib/api'

function parseTimestamp(ts: string): number {
  const parts = ts.split(':').map(Number)
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
  if (parts.length === 2) return parts[0] * 60 + parts[1]
  return 0
}

function parseTranscriptLine(line: string): { timestamp: string; text: string; seconds: number } | null {
  const match = line.match(/^\[([\d:]+)\s*-->\s*([\d:]+)\]\s*(.*)$/)
  if (!match) return null
  return { timestamp: match[1], text: match[3], seconds: parseTimestamp(match[1]) }
}

interface TranscriptPanelProps {
  recording: Recording
  transcriptSearch: string
  onTranscriptSearchChange: (value: string) => void
  onTranscribe: () => void
  isTranscribing: boolean
  onSeek?: (seconds: number) => void
  /** Render as a standalone panel (desktop) vs inline (mobile) */
  variant?: 'panel' | 'inline'
}

export default function TranscriptPanel({
  recording,
  transcriptSearch,
  onTranscriptSearchChange,
  onTranscribe,
  isTranscribing,
  onSeek,
  variant = 'inline',
}: TranscriptPanelProps) {
  const searchRef = useRef<HTMLInputElement>(null)

  const content = (
    <>
      {!recording.transcript_status && (
        <div className="flex flex-col items-center justify-center py-8 gap-3">
          <FileText className="h-8 w-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No transcript yet</p>
          <Button
            size="sm"
            onClick={onTranscribe}
            disabled={isTranscribing || recording.status === 'recording'}
          >
            {isTranscribing ? (
              <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Starting…</>
            ) : (
              'Transcribe'
            )}
          </Button>
        </div>
      )}

      {(recording.transcript_status === 'pending' || recording.transcript_status === 'processing') && (
        <div className="flex items-center gap-2 py-6 justify-center">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          <p className="text-sm text-muted-foreground capitalize">
            {recording.transcript_status}…
          </p>
        </div>
      )}

      {recording.transcript_status === 'failed' && (
        <div className="flex flex-col items-center gap-2 py-6">
          <p className="text-sm text-danger">Transcription failed.</p>
          <Button size="sm" variant="outline" onClick={onTranscribe}>
            Retry
          </Button>
        </div>
      )}

      {recording.transcript_status === 'done' && recording.transcript_text && (
        <>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              ref={searchRef}
              placeholder="Search transcript…"
              value={transcriptSearch}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => onTranscriptSearchChange(e.target.value)}
              className="pl-8 h-8 text-sm"
            />
          </div>
          <div className={`font-mono text-xs space-y-1 ${variant === 'panel' ? '' : 'max-h-80 overflow-y-auto rounded-lg border border-border bg-code p-3'}`}>
            {recording.transcript_text
              .split('\n')
              .filter((line: string) => !transcriptSearch || line.toLowerCase().includes(transcriptSearch.toLowerCase()))
              .map((line: string, i: number) => {
                const parsed = parseTranscriptLine(line)
                return (
                  <p
                    key={i}
                    className={`leading-relaxed ${
                      transcriptSearch && line.toLowerCase().includes(transcriptSearch.toLowerCase())
                        ? 'bg-indigo-500/25 rounded px-1'
                        : ''
                    }`}
                  >
                    {parsed ? (
                      <>
                        <button
                          onClick={() => onSeek?.(parsed.seconds)}
                          className="text-primary-ink hover:underline cursor-pointer"
                          title={`Jump to ${parsed.timestamp}`}
                        >
                          [{parsed.timestamp}]
                        </button>
                        {' '}{parsed.text}
                      </>
                    ) : (
                      line
                    )}
                  </p>
                )
              })}
          </div>
        </>
      )}
    </>
  )

  if (variant === 'panel') {
    return (
      <div className="hidden lg:flex w-80 shrink-0 flex-col border border-border rounded-xl overflow-hidden bg-card self-start max-h-[calc(100vh-6rem)]">
        <div className="px-4 py-3 border-b border-border bg-background flex items-center gap-2">
          <FileText className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">Transcript</span>
          {recording.transcript_status === 'done' && (
            <span className="ml-auto h-1.5 w-1.5 rounded-full bg-success" />
          )}
        </div>
        <div className="flex-1 p-3 space-y-3 overflow-y-auto min-h-0">
          {content}
        </div>
      </div>
    )
  }

  // Inline variant — just the content
  return <div className="p-4 space-y-3">{content}</div>
}
