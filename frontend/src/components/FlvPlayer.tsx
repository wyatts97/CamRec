import { useEffect, useRef, useCallback, useState, useMemo } from 'react'
import mpegts from 'mpegts.js'
import Hls from 'hls.js'

export type LiveStreamType = 'flv' | 'hls' | 'rtmp' | 'auto'

interface FlvPlayerProps {
  src: string | null
  type?: LiveStreamType
  className?: string
  autoPlay?: boolean
  muted?: boolean
  controls?: boolean
  onError?: () => void
  onReady?: () => void
}

function detectType(url: string | null, explicit: LiveStreamType): 'flv' | 'hls' | 'rtmp' | 'native' {
  if (explicit !== 'auto') return explicit as 'flv' | 'hls' | 'rtmp'
  if (!url) return 'native'
  const lower = url.toLowerCase()
  if (lower.endsWith('.m3u8') || lower.includes('/playlist') || lower.includes('/master')) return 'hls'
  if (lower.endsWith('.flv') || lower.includes('/flv')) return 'flv'
  if (lower.startsWith('rtmp://') || lower.startsWith('rtmps://')) return 'rtmp'
  if (lower.includes('hls') || lower.includes('m3u8')) return 'hls'
  if (lower.includes('flv')) return 'flv'
  return 'native'
}

export default function FlvPlayer({
  src,
  type = 'auto',
  className = '',
  autoPlay = false,
  muted = false,
  controls = true,
  onError,
  onReady,
}: FlvPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const flvPlayerRef = useRef<mpegts.Player | null>(null)
  const hlsRef = useRef<Hls | null>(null)
  const retryCountRef = useRef(0)
  const [error, setError] = useState(false)
  const [buffering, setBuffering] = useState(false)

  const streamType = useMemo(() => detectType(src, type), [src, type])

  const destroyPlayer = useCallback(() => {
    const flv = flvPlayerRef.current
    if (flv) {
      try {
        flv.pause()
        flv.unload()
        flv.detachMediaElement()
        flv.destroy()
      } catch {
        // ignore cleanup errors
      }
      flvPlayerRef.current = null
    }
    const hls = hlsRef.current
    if (hls) {
      try {
        hls.destroy()
      } catch {
        // ignore cleanup errors
      }
      hlsRef.current = null
    }
  }, [])

  const handleFatalError = useCallback(() => {
    setError(true)
    setBuffering(false)
    onError?.()
  }, [onError])

  const handleCanPlay = useCallback(() => {
    setError(false)
    setBuffering(false)
    retryCountRef.current = 0
    onReady?.()
  }, [onReady])

  const setupHls = useCallback(
    (video: HTMLVideoElement, url: string) => {
      if (video.canPlayType('application/vnd.apple.mpegurl')) {
        // Safari / iOS native HLS support
        video.src = url
        return
      }

      if (!Hls.isSupported()) {
        handleFatalError()
        return
      }

      const hls = new Hls({
        enableWorker: true,
        maxBufferLength: 30,
        liveBackBufferLength: 60,
        fragLoadingMaxRetry: 4,
        manifestLoadingMaxRetry: 4,
        levelLoadingMaxRetry: 4,
      })
      hls.loadSource(url)
      hls.attachMedia(video)

      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (data.fatal) {
          switch (data.type) {
            case Hls.ErrorTypes.NETWORK_ERROR:
              hls.startLoad()
              break
            case Hls.ErrorTypes.MEDIA_ERROR:
              hls.recoverMediaError()
              break
            default:
              handleFatalError()
              break
          }
        }
      })

      hls.on(Hls.Events.MANIFEST_PARSED, handleCanPlay)
      hls.on(Hls.Events.BUFFER_APPENDING, () => setBuffering(false))
      hlsRef.current = hls
    },
    [handleCanPlay, handleFatalError]
  )

  const setupFlv = useCallback(
    (video: HTMLVideoElement, url: string) => {
      if (!mpegts.getFeatureList().mseLivePlayback) {
        handleFatalError()
        return
      }

      const player = mpegts.createPlayer({
        type: 'flv',
        url,
        isLive: true,
      })

      player.on(mpegts.Events.ERROR, (_errType, _errDetail, errInfo) => {
        if (errInfo?.fatal ?? true) {
          handleFatalError()
        }
      })

      player.on(mpegts.Events.LOADING_COMPLETE, handleCanPlay)
      player.attachMediaElement(video)
      player.load()

      flvPlayerRef.current = player
    },
    [handleCanPlay, handleFatalError]
  )

  useEffect(() => {
    if (!src || !videoRef.current) return

    setError(false)
    setBuffering(true)
    retryCountRef.current = 0
    destroyPlayer()

    const video = videoRef.current
    video.src = ''
    video.load()

    if (streamType === 'hls') {
      setupHls(video, src)
    } else if (streamType === 'flv') {
      setupFlv(video, src)
    } else {
      // Native / rtmp fallback: just attach the URL and hope the browser
      // can play it (e.g. Safari HLS, or a direct MP4 stream)
      video.src = src
      video.load()
    }

    if (autoPlay) {
      const playPromise = video.play()
      playPromise?.catch(() => {
        // Autoplay may be blocked; user can click to play.
      })
    }

    return () => {
      destroyPlayer()
    }
  }, [src, streamType, autoPlay, setupHls, setupFlv, destroyPlayer])

  if (error) {
    return (
      <div className={`flex flex-col items-center justify-center gap-2 bg-gray-900 ${className}`}>
        <p className="text-gray-400 text-sm">Stream playback error</p>
        <p className="text-gray-500 text-xs text-center px-4">
          {streamType === 'hls' ? 'HLS stream failed to load' : 'FLV stream failed to load'}
        </p>
      </div>
    )
  }

  return (
    <div className={`relative ${className}`}>
      <video
        ref={videoRef}
        className="w-full h-full object-contain bg-black"
        controls={controls}
        muted={muted}
        playsInline
        onWaiting={() => setBuffering(true)}
        onPlaying={() => setBuffering(false)}
        onCanPlay={handleCanPlay}
        onError={handleFatalError}
      />
      {buffering && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/40 pointer-events-none">
          <div className="h-8 w-8 border-2 border-white/30 border-t-white rounded-full animate-spin" />
        </div>
      )}
    </div>
  )
}
