import { NavLink, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Clapperboard } from 'lucide-react'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupTitle,
  SidebarHeader,
  SidebarItem,
  SidebarItemButton,
  SidebarList,
  SidebarLogo,
  SidebarMenu,
} from '@/components/selia/sidebar'
import { Progress, ProgressLabel, ProgressValue } from '@/components/selia/progress'
import { Badge } from '@/components/selia/badge'
import { IconBox } from '@/components/selia/icon-box'
import { api } from '@/lib/api'
import { cn, formatBytes } from '@/lib/utils'
import { NAV_GROUPS, NAV_ITEMS, isNavActive } from '@/lib/nav'

/**
 * The app's navigation, built from Selia's Sidebar.
 *
 * Rendered by Layout twice: as the fixed desktop sidebar and inside the mobile
 * drawer. `onNavigate` lets the drawer close itself after a tap.
 */
export default function SidebarNav({
  onNavigate,
  className,
}: {
  onNavigate?: () => void
  className?: string
}) {
  const { pathname } = useLocation()

  // Shared cache with Live/Dashboard; kept fresh by useNotificationStream.
  const { data: activeRecordings = [] } = useQuery({
    queryKey: ['activeRecordings'],
    queryFn: () => api.recordings.getActive(),
    refetchInterval: 30000,
  })

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.settings.health(),
    refetchInterval: 60000,
  })

  const settingsItem = NAV_ITEMS.find((item) => item.group === null)

  return (
    <Sidebar className={cn('h-full', className)}>
      <SidebarHeader>
        <SidebarLogo>
          <IconBox variant="secondary-subtle" size="sm">
            <Clapperboard />
          </IconBox>
          <span className="font-semibold tracking-tight">TikRec</span>
        </SidebarLogo>
      </SidebarHeader>

      <SidebarContent>
        <SidebarMenu aria-label="Main">
          {NAV_GROUPS.map((group) => (
            <SidebarGroup key={group} aria-label={group}>
              <SidebarGroupTitle>{group}</SidebarGroupTitle>
              <SidebarList>
                {NAV_ITEMS.filter((item) => item.group === group).map((item) => {
                  const Icon = item.icon
                  const active = isNavActive(pathname, item.to)
                  const liveCount = item.to === '/live' ? activeRecordings.length : 0
                  return (
                    <SidebarItem key={item.to}>
                      <SidebarItemButton
                        active={active}
                        render={
                          <NavLink
                            to={item.to}
                            end={item.to === '/'}
                            onClick={onNavigate}
                            aria-current={active ? 'page' : undefined}
                          />
                        }
                      >
                        <Icon />
                        <span className="flex-1">{item.label}</span>
                        {liveCount > 0 && (
                          <Badge size="sm" variant="secondary" aria-label={`${liveCount} recording now`}>
                            {liveCount}
                          </Badge>
                        )}
                      </SidebarItemButton>
                    </SidebarItem>
                  )
                })}
              </SidebarList>
            </SidebarGroup>
          ))}
        </SidebarMenu>
      </SidebarContent>

      <SidebarFooter className="flex flex-col gap-3">
        {health?.disk_usage && <StorageProgress usage={health.disk_usage} onNavigate={onNavigate} />}
        {settingsItem && (
          <SidebarList>
            <SidebarItem>
              <SidebarItemButton
                active={isNavActive(pathname, settingsItem.to)}
                render={<NavLink to={settingsItem.to} onClick={onNavigate} />}
              >
                <settingsItem.icon />
                {settingsItem.label}
              </SidebarItemButton>
            </SidebarItem>
          </SidebarList>
        )}
      </SidebarFooter>
    </Sidebar>
  )
}

function StorageProgress({
  usage,
  onNavigate,
}: {
  usage: { total: number; used: number; free: number; percent: number }
  onNavigate?: () => void
}) {
  const freePercent = 100 - usage.percent
  return (
    <NavLink
      to="/storage"
      onClick={onNavigate}
      className="block rounded-lg p-2.5 -mx-2.5 hover:bg-accent transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      aria-label={`Storage: ${formatBytes(usage.free)} free of ${formatBytes(usage.total)}`}
    >
      <Progress
        value={usage.percent}
        // Same low-space thresholds the old dashboard storage card used.
        className={cn(
          freePercent <= 20 && freePercent > 10 && '**:data-[slot=progress-indicator]:bg-warning',
          freePercent <= 10 && '**:data-[slot=progress-indicator]:bg-danger',
        )}
      >
        <ProgressLabel className="text-sm">Storage</ProgressLabel>
        <ProgressValue>{() => `${formatBytes(usage.free)} free`}</ProgressValue>
      </Progress>
    </NavLink>
  )
}
