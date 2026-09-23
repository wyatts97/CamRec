export const API_BASE = "/api"

/** Thrown on a 401 so callers (and the query cache) can tell auth failures apart. */
export class UnauthorizedError extends Error {
  constructor(message = "Authentication required") {
    super(message)
    this.name = "UnauthorizedError"
  }
}

type UnauthorizedHandler = () => void
let onUnauthorized: UnauthorizedHandler | null = null

/** Registered once by AuthProvider so a 401 anywhere can bounce us to /login. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  onUnauthorized = handler
}

/**
 * Report a dead session from a transport that can't surface a 401 itself.
 * EventSource is the case that matters: it exposes neither status nor body,
 * so the SSE hook has to detect the failure and say so explicitly.
 */
export function notifyUnauthorized() {
  onUnauthorized?.()
}

async function fetchApi<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    // Spread caller options FIRST so the merged headers below survive. The
    // other order silently dropped Content-Type (and credentials) the moment
    // any caller passed its own `headers`.
    ...options,
    // The session lives in an HttpOnly cookie; it must ride along on every call.
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  })

  if (response.status === 401) {
    onUnauthorized?.()
    throw new UnauthorizedError()
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed" }))
    throw new Error(error.detail || "Request failed")
  }

  if (response.status === 204) {
    return undefined as T
  }

  // A 200 with a non-JSON body (proxy interstitial, truncated response) used
  // to surface to the user as "Unexpected token < in JSON at position 0".
  try {
    return (await response.json()) as T
  } catch {
    throw new Error("Server returned an unreadable response")
  }
}

export interface ExportJob {
  id: string
  status: 'pending' | 'running' | 'ready' | 'failed' | 'cancelled'
  files_done: number
  total_files: number
  bytes_done: number
  total_bytes: number
  percent: number
  error: string | null
  filename: string
  created_at: string
}

export interface AuthStatus {
  authenticated: boolean
  auth_enabled: boolean
}

export interface User {
  id: number
  username: string
  display_name: string | null
  bio: string | null
  follower_count: number | null
  profile_pic_url: string | null
  room_id: string | null
  is_monitoring: boolean
  is_live: boolean
  last_checked: string | null
  created_at: string
  updated_at: string
}

export interface Recording {
  id: number
  user_id: number
  username: string
  filename: string
  status: string
  mode: string
  started_at: string | null
  ended_at: string | null
  duration_seconds: number | null
  file_size: number | null
  error_message: string | null
  created_at: string
  thumbnail_ready: boolean
  sprite_ready: boolean
  transcript_status: string | null
  /** Only populated by the single-recording endpoint; always null in list responses. */
  transcript_text: string | null
  is_favorite: boolean
  is_corrupt?: boolean
}

export interface RecordingListResponse {
  recordings: Recording[]
  total: number
  page: number
  page_size: number
}

export interface Clip {
  id: number
  /** null once the source recording has been deleted -- clips outlive it. */
  recording_id: number | null
  username: string
  title: string | null
  filename: string
  start_time: number
  end_time: number
  duration_seconds: number | null
  file_size: number | null
  thumbnail_ready: boolean
  sprite_ready: boolean
  is_favorite: boolean
  created_at: string
}

export interface LiveEvent {
  id: number
  recording_id: number
  offset_seconds: number
  event_type: "chat" | "gift"
  user_nickname: string
  user_unique_id: string | null
  content: string | null
  gift_name: string | null
  gift_diamond_count: number | null
  gift_repeat_count: number | null
  created_at: string
}

export interface LiveEventListResponse {
  events: LiveEvent[]
  total: number
}

export interface ClipListResponse {
  clips: Clip[]
  total: number
  page: number
  page_size: number
}

export interface ActiveRecording {
  id: number
  user_id: number
  username: string
  status: string
  started_at: string | null
  duration_seconds: number | null
  room_id: string | null
  chat_connected: boolean
  /** Why chat is not being captured, when chat_connected is false. */
  chat_error: string | null
}

export interface AutoCleanupConfig {
  enabled: boolean
  days: number
  action: "delete" | "compress"
}

export interface Settings {
  cookies: {
    /** Masked preview only (e.g. "••••••••1a2b"). Submitting it back unchanged
     *  keeps the stored value; the full token is never sent to the client. */
    sessionid_ss: string
    tt_target_idc: string
    sessionid_ss_set?: boolean
  }
  telegram: {
    api_id: string
    /** Masked preview only -- see cookies.sessionid_ss. */
    api_hash: string
    chat_id: string
    api_hash_set?: boolean
  }
  proxy: string | null
  output_dir: string
  default_bitrate: string | null
  automatic_interval: number
  /** Send the session ID to the Euler Stream sign server for chat capture. */
  chat_authenticated: boolean
  auto_cleanup: AutoCleanupConfig
  timezone: string
}

export interface DiskUsage {
  total: number
  used: number
  free: number
  percent: number
}

export interface HealthStatus {
  status: string
  recorder_available: boolean
  country_blacklisted: boolean
  cookies_configured: boolean
  recordings_dir: string
  recordings_dir_exists: boolean
  disk_usage: DiskUsage | null
  cpu_percent: number | null
  ram_percent: number | null
}

export interface MonitorStatus {
  is_running: boolean
  last_check_at: string | null
  next_check_in_seconds: number | null
  interval_minutes: number
  check_interval: number
}

export interface StatsOverview {
  total_recordings: number
  total_hours: number
  total_seconds: number
  total_storage: number
  clip_storage: number
  total_clips: number
  total_users: number
  monitored_users: number
  total_chat_messages: number
  total_gifts: number
  total_diamonds: number
}

export interface RecordingsPerDay {
  date: string
  count: number
  hours: number
}

export interface TopStreamer {
  user_id: number
  username: string
  count: number
  hours: number
}

export interface StorageByUser {
  user_id: number
  username: string
  count: number
  bytes: number
}

export interface GiftChatVolume {
  recording_id: number
  username: string
  chat_count: number
  gift_count: number
  diamonds: number
}

export interface LargestRecording {
  id: number
  username: string
  filename: string
  file_size: number
  duration_seconds: number | null
  status: string
  created_at: string
}

export interface DiskUsage {
  total: number
  used: number
  free: number
  percent: number
}

export interface StorageStats {
  total_storage: number
  recording_storage: number
  clip_storage: number
  backup_storage: number
  backup_count: number
  total_recordings: number
  total_clips: number
  disk_usage: DiskUsage | null
}

export interface AppNotification {
  id: number
  type: string
  title: string
  message: string
  data: Record<string, any>
  created_at: string
  read: boolean
}

export interface LiveClipStatus {
  active: boolean
  elapsed: number
  error?: string | null
  clip_id?: number
  duration_seconds?: number
}

export interface GlobalSearchResult {
  query: string
  transcripts: {
    recording_id: number
    username: string
    match_count: number
    matches: { offset_seconds: number; snippet: string }[]
  }[]
  events: {
    id: number
    recording_id: number
    username: string
    offset_seconds: number
    event_type: "chat" | "gift"
    user_nickname: string
    content: string | null
    gift_name: string | null
  }[]
  transcript_count: number
  event_count: number
}

export const api = {
  users: {
    list: (monitoringOnly = false, watchlistOnly = true) =>
      fetchApi<User[]>(`/users?monitoring_only=${monitoringOnly}&watchlist_only=${watchlistOnly}`),
    
    create: (username: string, isMonitoring = false) =>
      fetchApi<User>("/users", {
        method: "POST",
        body: JSON.stringify({ username, is_monitoring: isMonitoring }),
      }),
    
    get: (id: number) => fetchApi<User>(`/users/${id}`),
    
    update: (id: number, data: { is_monitoring?: boolean; room_id?: string }) =>
      fetchApi<User>(`/users/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    
    removeFromWatchlist: (id: number) =>
      fetchApi<User>(`/users/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_on_watchlist: false }),
      }),
    delete: (id: number) =>
      fetchApi<void>(`/users/${id}`, { method: "DELETE" }),
    
    checkStatus: (id: number) =>
      fetchApi<{ username: string; is_live: boolean; room_id: string | null; last_checked: string }>(
        `/users/${id}/status`
      ),
    
    refresh: (id: number, refreshProfile = false) =>
      fetchApi<User>(`/users/${id}/refresh?refresh_profile=${refreshProfile}`, { method: "POST" }),
    
    getAvatarUrl: (id: number) => `${API_BASE}/users/${id}/avatar`,
  },

  recordings: {
    list: (
      page = 1,
      pageSize = 20,
      statusFilter?: string,
      userId?: number,
      filters?: {
        sortBy?: string
        sortOrder?: string
        usernameFilter?: string
        minSize?: number
        maxSize?: number
        dateFrom?: string
        dateTo?: string
        favoritesOnly?: boolean
      }
    ) => {
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: pageSize.toString(),
      })
      if (statusFilter) params.set("status_filter", statusFilter)
      if (userId) params.set("user_id", userId.toString())
      if (filters?.sortBy) params.set("sort_by", filters.sortBy)
      if (filters?.sortOrder) params.set("sort_order", filters.sortOrder)
      if (filters?.usernameFilter) params.set("username_filter", filters.usernameFilter)
      if (filters?.minSize !== undefined) params.set("min_size", filters.minSize.toString())
      if (filters?.maxSize !== undefined) params.set("max_size", filters.maxSize.toString())
      if (filters?.dateFrom) params.set("date_from", filters.dateFrom)
      if (filters?.dateTo) params.set("date_to", filters.dateTo)
      if (filters?.favoritesOnly) params.set("favorites_only", "true")
      return fetchApi<RecordingListResponse>(`/recordings?${params}`)
    },
    
    start: (data: {
      username?: string
      url?: string
      room_id?: string
      mode?: string
      duration?: number
      bitrate?: string
    }) =>
      fetchApi<Recording>("/recordings/start", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    
    get: (id: number) => fetchApi<Recording>(`/recordings/${id}`),
    
    stop: (id: number) =>
      fetchApi<Recording>(`/recordings/${id}/stop`, { method: "POST" }),
    
    delete: (id: number) =>
      fetchApi<void>(`/recordings/${id}`, { method: "DELETE" }),
    
    getActive: () => fetchApi<ActiveRecording[]>("/recordings/active"),

    getLiveUrl: (id: number) =>
      fetchApi<{ live_url: string; type: 'hls' | 'flv' | 'rtmp' }>(`/recordings/${id}/live-url`),

    toggleFavorite: (id: number) =>
      fetchApi<Recording>(`/recordings/${id}/favorite`, { method: "POST" }),

    getDownloadUrl: (id: number) => `${API_BASE}/recordings/${id}/download`,
    getStreamUrl: (id: number) => `${API_BASE}/recordings/${id}/stream`,
    getThumbnailUrl: (id: number, version?: string | number | null) => {
      const url = `${API_BASE}/recordings/${id}/thumbnail`
      return version ? `${url}?v=${encodeURIComponent(String(version))}` : url
    },
    getSpriteVttUrl: (id: number) => `${API_BASE}/recordings/${id}/thumbnails.vtt`,

    transcribe: (id: number) =>
      fetchApi<Recording>(`/recordings/${id}/transcribe`, { method: "POST" }),

    searchTranscripts: (q: string) =>
      fetchApi<{ recording_id: number; username: string; snippet: string }[]>(
        `/recordings/transcripts/search?q=${encodeURIComponent(q)}`
      ),
    
    batchDelete: (ids: number[]) =>
      fetchApi<{ deleted: number; errors: string[] }>("/recordings/batch/delete", {
        method: "POST",
        body: JSON.stringify({ recording_ids: ids }),
      }),

    stopAll: () =>
      fetchApi<{ stopped: number }>("/recordings/stop-all", { method: "POST" }),

    batchCompress: (ids: number[]) =>
      fetchApi<{ compressed: number; deleted: number; backup_file: string }>(
        "/recordings/batch/compress",
        { method: "POST", body: JSON.stringify({ recording_ids: ids }) }
      ),

    liveClipStatus: (id: number) =>
      fetchApi<LiveClipStatus>(`/recordings/${id}/live-clip/status`),

    liveClipStart: (id: number) =>
      fetchApi<LiveClipStatus>(`/recordings/${id}/live-clip/start`, { method: "POST" }),

    liveClipStop: (id: number) =>
      fetchApi<LiveClipStatus>(`/recordings/${id}/live-clip/stop`, { method: "POST" }),
    
    /**
     * @param afterId Return only events newer than this id. Lets the chat
     * panel poll for deltas instead of re-downloading the whole window.
     */
    getEvents: (id: number, page = 1, pageSize = 100, eventType?: string, search?: string, afterId?: number) => {
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: pageSize.toString(),
      })
      if (eventType) params.set("event_type", eventType)
      if (search) params.set("search", search)
      if (afterId !== undefined) params.set("after_id", afterId.toString())
      return fetchApi<LiveEventListResponse>(`/recordings/${id}/events?${params}`)
    },

    repair: (id: number) =>
      fetchApi<Recording>(`/recordings/${id}/repair`, { method: "POST" }),


  },

  clips: {
    create: (data: {
      recording_id: number
      start_time: number
      end_time: number
      title?: string | null
    }) =>
      fetchApi<Clip>("/clips", {
        method: "POST",
        body: JSON.stringify(data),
      }),

    list: (
      page = 1,
      pageSize = 20,
      sortBy?: string,
      sortOrder?: string,
      recordingId?: number,
      filters?: {
        search?: string
        favoritesOnly?: boolean
      }
    ) => {
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: pageSize.toString(),
      })
      if (sortBy) params.set("sort_by", sortBy)
      if (sortOrder) params.set("sort_order", sortOrder)
      if (recordingId != null) params.set("recording_id", recordingId.toString())
      if (filters?.search) params.set("search", filters.search)
      if (filters?.favoritesOnly) params.set("favorites_only", "true")
      return fetchApi<ClipListResponse>(`/clips?${params}`)
    },

    get: (id: number) => fetchApi<Clip>(`/clips/${id}`),

    delete: (id: number) => fetchApi<void>(`/clips/${id}`, { method: "DELETE" }),

    toggleFavorite: (id: number) =>
      fetchApi<Clip>(`/clips/${id}/favorite`, { method: "POST" }),

    updateTitle: (id: number, title: string | null) =>
      fetchApi<Clip>(`/clips/${id}?title=${encodeURIComponent(title || "")}`, {
        method: "PATCH",
      }),

    getDownloadUrl: (id: number) => `${API_BASE}/clips/${id}/download`,
    getStreamUrl: (id: number) => `${API_BASE}/clips/${id}/stream`,
    getThumbnailUrl: (id: number, version?: string | number | null) => {
      const url = `${API_BASE}/clips/${id}/thumbnail`
      return version ? `${url}?v=${encodeURIComponent(String(version))}` : url
    },
    getSpriteVttUrl: (id: number) => `${API_BASE}/clips/${id}/thumbnails.vtt`,

    batchDelete: (ids: number[]) =>
      fetchApi<{ deleted: number; errors: string[] }>("/clips/batch/delete", {
        method: "POST",
        body: JSON.stringify({ clip_ids: ids }),
      }),


  },

  settings: {
    get: () => fetchApi<Settings>("/settings"),
    
    update: (data: Partial<Settings>) =>
      fetchApi<Settings>("/settings", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    
    health: () => fetchApi<HealthStatus>("/settings/health"),
    
    getCleanupStats: () => 
      fetchApi<{ count: number; total_size: number; days: number }>("/settings/cleanup/stats"),
    
    runCleanup: () =>
      fetchApi<{ status: string; deleted: number; compressed: number; backup_file?: string }>(
        "/settings/cleanup/run",
        { method: "POST" }
      ),

    getMonitorStatus: () =>
      fetchApi<MonitorStatus>("/settings/monitor-status"),

    triggerMonitorCheck: () =>
      fetchApi<{ triggered: boolean }>("/settings/monitor-check", { method: "POST" }),
  },

  stats: {
    overview: () => fetchApi<StatsOverview>("/stats/overview"),
    recordingsPerDay: (days = 30) =>
      fetchApi<RecordingsPerDay[]>(`/stats/recordings-per-day?days=${days}`),
    topStreamers: (limit = 10) =>
      fetchApi<TopStreamer[]>(`/stats/top-streamers?limit=${limit}`),
    storageByUser: (limit = 20) =>
      fetchApi<StorageByUser[]>(`/stats/storage-by-user?limit=${limit}`),
    giftChatVolume: (limit = 10) =>
      fetchApi<GiftChatVolume[]>(`/stats/gift-chat-volume?limit=${limit}`),
    largestRecordings: (limit = 20) =>
      fetchApi<LargestRecording[]>(`/stats/largest-recordings?limit=${limit}`),
    storage: () => fetchApi<StorageStats>("/stats/storage"),
  },

  notifications: {
    list: (limit = 50) =>
      fetchApi<{ notifications: AppNotification[]; unread: number }>(
        `/notifications?limit=${limit}`
      ),
    markAllRead: () =>
      fetchApi<{ unread: number }>("/notifications/read", { method: "POST" }),
    streamUrl: () => `${API_BASE}/notifications/stream`,
  },

  search: {
    global: (q: string, limit = 50) =>
      fetchApi<GlobalSearchResult>(
        `/search?q=${encodeURIComponent(q)}&limit=${limit}`
      ),
  },

  exports: {
    /** Queue a ZIP export. Omit `ids` to export everything of that kind. */
    create: (kind: 'recordings' | 'clips', ids?: number[]) =>
      fetchApi<ExportJob>("/exports", {
        method: "POST",
        body: JSON.stringify({ kind, ids: ids ?? null }),
      }),
    get: (id: string) => fetchApi<ExportJob>(`/exports/${id}`),
    cancel: (id: string) =>
      fetchApi<{ cancelled: boolean }>(`/exports/${id}`, { method: "DELETE" }),
    downloadUrl: (id: string) => `${API_BASE}/exports/${id}/download`,
  },

  auth: {
    status: () => fetchApi<AuthStatus>("/auth/status"),
    login: (password: string) =>
      fetchApi<AuthStatus>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ password }),
      }),
    logout: () => fetchApi<AuthStatus>("/auth/logout", { method: "POST" }),
  },
}
