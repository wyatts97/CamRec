import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, setUnauthorizedHandler } from '@/lib/api'

interface AuthContextValue {
  /** null while the initial status probe is in flight. */
  isAuthenticated: boolean | null
  /** False when the backend runs with AUTH_ENABLED=false. */
  authEnabled: boolean
  login: (password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null)
  const [authEnabled, setAuthEnabled] = useState(true)
  const queryClient = useQueryClient()

  // Any 401 from any request drops us back to the login screen, so an expired
  // session doesn't leave the UI showing stale data behind failing polls.
  useEffect(() => {
    setUnauthorizedHandler(() => setIsAuthenticated(false))
    return () => setUnauthorizedHandler(null)
  }, [])

  useEffect(() => {
    let cancelled = false
    api.auth
      .status()
      .then((s) => {
        if (cancelled) return
        setIsAuthenticated(s.authenticated)
        setAuthEnabled(s.auth_enabled)
      })
      .catch(() => {
        if (!cancelled) setIsAuthenticated(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(
    async (password: string) => {
      const s = await api.auth.login(password)
      setIsAuthenticated(s.authenticated)
      setAuthEnabled(s.auth_enabled)
      // Nothing cached before login is trustworthy for this session.
      queryClient.clear()
    },
    [queryClient]
  )

  const logout = useCallback(async () => {
    try {
      await api.auth.logout()
    } finally {
      setIsAuthenticated(false)
      queryClient.clear()
    }
  }, [queryClient])

  const value = useMemo(
    () => ({ isAuthenticated, authEnabled, login, logout }),
    [isAuthenticated, authEnabled, login, logout]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
