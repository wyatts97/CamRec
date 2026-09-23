import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import { ThemeProvider } from './hooks/useTheme'
import ErrorBoundary from './components/ErrorBoundary'
import Layout from './components/Layout'
import { Toaster } from 'react-hot-toast'
import { TimezoneProvider } from './lib/timezone-context'
import { AuthProvider, useAuth } from './hooks/useAuth'
import NotFound from './pages/NotFound'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const Watchlist = lazy(() => import('./pages/Watchlist'))
const Recordings = lazy(() => import('./pages/Recordings'))
const Watch = lazy(() => import('./pages/Watch'))
const WatchPlayer = lazy(() => import('./pages/WatchPlayer'))
const Live = lazy(() => import('./pages/Live'))
const LivePlayer = lazy(() => import('./pages/LivePlayer'))
const Clips = lazy(() => import('./pages/Clips'))
const ClipPlayer = lazy(() => import('./pages/ClipPlayer'))
const Settings = lazy(() => import('./pages/Settings'))
const Storage = lazy(() => import('./pages/Storage'))
const Login = lazy(() => import('./pages/Login'))

function FullscreenSpinner() {
  return (
  <div className="flex h-screen items-center justify-center" role="status" aria-label="Loading">
    <svg className="h-7 w-7 animate-spin motion-reduce:animate-none text-primary-ink" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
    <span className="sr-only">Loading…</span>
  </div>
  )
}

/** Renders the app only once a session is confirmed; otherwise the login screen. */
function AuthGate({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth()

  // null = the status probe has not resolved yet. Rendering the app here would
  // fire a burst of requests that all 401 and flood the user with error toasts.
  if (isAuthenticated === null) return <FullscreenSpinner />
  if (!isAuthenticated) return <Login />
  return <>{children}</>
}

function ToasterWrapper() {
  return (
    <Toaster
      position="bottom-right"
      toastOptions={{
        style: {
          background: 'var(--color-popover)',
          color: 'var(--color-popover-foreground)',
          border: '1px solid var(--color-border)',
          boxShadow: 'var(--shadow-lg)',
          borderRadius: '0.75rem',
          padding: '0.75rem 1rem',
          fontSize: '0.875rem',
        },
        success: {
          iconTheme: {
            primary: 'var(--color-success)',
            secondary: 'var(--color-popover)',
          },
        },
        error: {
          iconTheme: {
            primary: 'var(--color-danger)',
            secondary: 'var(--color-popover)',
          },
        },
      }}
    />
  )
}

function App() {
  return (
    <ErrorBoundary>
    <AuthProvider>
    <ThemeProvider>
      <TimezoneProvider>
      <Suspense fallback={<FullscreenSpinner />}>
        <AuthGate>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="watchlist" element={<Watchlist />} />
            <Route path="recordings" element={<Recordings />} />
            <Route path="watch" element={<Watch />} />
            <Route path="watch/:id" element={<WatchPlayer />} />
            <Route path="live" element={<Live />} />
            <Route path="live/:id" element={<LivePlayer />} />
            <Route path="clips" element={<Clips />} />
            <Route path="clips/:id" element={<ClipPlayer />} />
            <Route path="storage" element={<Storage />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
        </AuthGate>
      </Suspense>
      </TimezoneProvider>
      <ToasterWrapper />
    </ThemeProvider>
    </AuthProvider>
    </ErrorBoundary>
  )
}

export default App
