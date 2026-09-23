import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
// Route icons come from lib/nav.ts; Search is the input's own affordance.
import { Search } from 'lucide-react'
import {
  Command,
  CommandContent,
  CommandBody,
} from 'components/selia/command'
import { Input } from 'components/selia/input'
import { cn } from '@/lib/utils'
import { NAV_ITEMS as routes } from '@/lib/nav'


export default function CommandPalette() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')

  useEffect(() => {
    function down(e: KeyboardEvent) {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen((prev) => {
          if (!prev) setSearch('')
          return !prev
        })
      }
    }
    document.addEventListener('keydown', down)
    return () => document.removeEventListener('keydown', down)
  }, [])

  const filtered = useMemo(() => {
    if (!search.trim()) return routes
    const q = search.toLowerCase()
    return routes.filter((r) => r.label.toLowerCase().includes(q))
  }, [search])

  function handleSelect(to: string) {
    navigate(to)
    setOpen(false)
    setSearch('')
  }

  return (
    <Command open={open} onOpenChange={(o) => { setOpen(o); if (!o) setSearch('') }}>
      <CommandContent className="max-h-[min(27rem,50dvh)]">
        <CommandBody>
          <div className="relative p-2.5 border-b border-dialog-border">
            <Search className="absolute left-5 top-1/2 -translate-y-1/2 h-4 w-4 text-dimmed" />
            <Input
              placeholder="Type a command or search…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8 h-9 text-sm"
            />
          </div>
          <div className="px-2.5 py-1.5 space-y-0.5 max-h-[min(20rem,40dvh)] overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="flex items-center justify-center px-3 py-2.5 text-muted text-sm">
                No results found.
              </div>
            ) : (
              filtered.map((r) => {
                const Icon = r.icon
                return (
                  <button
                    key={r.to}
                    onClick={() => handleSelect(r.to)}
                    className={cn(
                      'flex items-center gap-3.5 w-full px-3 py-2.5 rounded cursor-pointer text-sm text-left',
                      'hover:bg-popover-accent focus-visible:outline-none focus-visible:bg-popover-accent',
                      '[&_svg]:size-4',
                    )}
                  >
                    <Icon className="text-foreground" />
                    <span>{r.label}</span>
                  </button>
                )
              })
            )}
          </div>
        </CommandBody>
      </CommandContent>
    </Command>
  )
}
