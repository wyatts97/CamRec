import React, { createContext, useContext } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { formatDate } from './utils'

const TimezoneContext = createContext<string>('UTC')

export function TimezoneProvider({ children }: { children: React.ReactNode }) {
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.settings.get(),
    staleTime: 60_000,
  })

  return (
    <TimezoneContext.Provider value={settings?.timezone ?? 'UTC'}>
      {children}
    </TimezoneContext.Provider>
  )
}

export function useTimezone(): string {
  return useContext(TimezoneContext)
}

export function useDateFormat(): (date: string | Date | null | undefined) => string {
  const tz = useTimezone()
  return (date) => formatDate(date, tz)
}
