import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { UnauthorizedError } from './lib/api'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      // Service worker registration failed — offline support unavailable
    })
  })
}

const queryClient = new QueryClient({
  // A single toast for any failed query. Most pages render only their empty
  // state on error, so without this an unreachable API was silent -- the UI
  // just looked empty. Deduped by key so a 5s poll can't spam the user.
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (error instanceof UnauthorizedError) return // handled by AuthProvider
      const message = error instanceof Error ? error.message : 'Request failed'
      toast.error(message, { id: `query-error-${String(query.queryKey[0])}` })
    },
  }),
  // The query-side counterpart above only covers reads. A mutation without
  // its own onError was completely silent: clicking "Transcribe" or the
  // sidebar sync and having it fail produced no toast, no log, nothing.
  // Mutations that define onError themselves still win -- this is only the
  // fallback for the ones that don't.
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) => {
      if (mutation.options.onError) return
      if (error instanceof UnauthorizedError) return // handled by AuthProvider
      const message = error instanceof Error ? error.message : 'Action failed'
      toast.error(message)
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 1000 * 30,
      retry: 1,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)

