import { useCallback, useEffect, useRef, useState } from 'react'
import toast from 'react-hot-toast'
import { api, type ExportJob } from '@/lib/api'

/**
 * Drives a background ZIP export and polls it to completion.
 *
 * Exports used to run inside the request: the browser sat on a dead connection
 * for minutes with no feedback. The job reports byte-level progress so the
 * caller can render a real progress bar.
 */
export function useExportJob() {
  const [job, setJob] = useState<ExportJob | null>(null)
  const [starting, setStarting] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancelled = useRef(false)

  const clearTimer = () => {
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
  }

  useEffect(() => {
    cancelled.current = false
    return () => {
      cancelled.current = true
      clearTimer()
    }
  }, [])

  const poll = useCallback((id: string) => {
    clearTimer()
    timer.current = setTimeout(async () => {
      if (cancelled.current) return
      try {
        const next = await api.exports.get(id)
        if (cancelled.current) return
        setJob(next)

        if (next.status === 'ready') {
          // Navigating to the URL lets the browser own the download; the
          // server deletes the archive once the response is sent.
          window.location.href = api.exports.downloadUrl(id)
          toast.success('Export ready')
          setJob(null)
          return
        }
        if (next.status === 'failed') {
          toast.error(next.error || 'Export failed')
          setJob(null)
          return
        }
        if (next.status === 'cancelled') {
          setJob(null)
          return
        }
        poll(id)
      } catch (err) {
        if (cancelled.current) return
        toast.error(err instanceof Error ? err.message : 'Export failed')
        setJob(null)
      }
    }, 1000)
  }, [])

  const start = useCallback(
    async (kind: 'recordings' | 'clips', ids?: number[]) => {
      if (starting || job) return
      setStarting(true)
      try {
        const created = await api.exports.create(kind, ids)
        setJob(created)
        poll(created.id)
      } catch (err) {
        toast.error(err instanceof Error ? err.message : 'Could not start export')
      } finally {
        setStarting(false)
      }
    },
    [starting, job, poll]
  )

  const cancel = useCallback(async () => {
    if (!job) return
    clearTimer()
    const id = job.id
    setJob(null)
    try {
      await api.exports.cancel(id)
    } catch {
      /* The job is already gone from the user's point of view. */
    }
  }, [job])

  return { job, starting, start, cancel, isExporting: starting || job !== null }
}
