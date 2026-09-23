import { useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Clapperboard, Menu } from 'lucide-react'
import { AnimatePresence } from 'framer-motion'
import { PageTransition } from '@/components/motion'
import CommandPalette from '@/components/CommandPalette'
import SidebarNav from '@/components/SidebarNav'
import { useNotificationStream } from '@/hooks/useNotificationStream'
import { Button } from '@/components/selia/button'
import { IconBox } from '@/components/selia/icon-box'
import { Drawer, DrawerPopup } from '@/components/selia/drawer'

export default function Layout() {
  const location = useLocation()
  const [drawerOpen, setDrawerOpen] = useState(false)

  // Mounted once, here: it refreshes queries on recording events and raises
  // desktop notifications.
  useNotificationStream()

  return (
    <div className="min-h-screen bg-background">
      <CommandPalette />

      {/* Mobile header */}
      <header className="fixed top-0 inset-x-0 z-40 bg-background/90 backdrop-blur border-b border-border md:hidden">
        <div className="flex items-center justify-between h-14 px-4">
          <div className="flex items-center gap-2.5">
            <IconBox variant="secondary-subtle" size="sm">
              <Clapperboard />
            </IconBox>
            <span className="text-lg font-semibold tracking-tight text-foreground">TikRec</span>
          </div>
          <Button
            variant="plain"
            size="icon"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open menu"
            aria-expanded={drawerOpen}
          >
            <Menu />
          </Button>
        </div>
      </header>

      {/* Mobile navigation drawer (swipe or Esc to close) */}
      <Drawer open={drawerOpen} onOpenChange={setDrawerOpen} swipeDirection="left">
        <DrawerPopup direction="left" className="max-w-72 md:hidden">
          <SidebarNav onNavigate={() => setDrawerOpen(false)} />
        </DrawerPopup>
      </Drawer>

      {/* Desktop sidebar */}
      <div className="hidden md:block md:fixed md:inset-y-0 md:left-0 md:z-30 md:w-64 border-r border-border bg-background">
        <SidebarNav />
      </div>

      <main className="md:pl-64 pt-14 md:pt-0 pb-8">
        <div className="px-4 sm:px-6 lg:px-8 py-6 max-w-7xl mx-auto">
          <AnimatePresence mode="wait" initial={false}>
            <PageTransition key={location.pathname}>
              <Outlet />
            </PageTransition>
          </AnimatePresence>
        </div>
      </main>
    </div>
  )
}
