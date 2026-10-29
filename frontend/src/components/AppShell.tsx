import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bot,
  BookOpen,
  FolderKanban,
  LayoutDashboard,
  ListTodo,
  LogOut,
  MessageCircleQuestion,
  Moon,
  Package,
  Search,
  Sun,
} from 'lucide-react'
import { useTheme } from 'next-themes'
import { NavLink, Outlet, useNavigate } from 'react-router'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import { clearToken } from '@/lib/auth'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/projects', label: 'Projects', icon: FolderKanban },
  { to: '/tasks', label: 'Tasks', icon: ListTodo },
  { to: '/runs', label: 'Agent Runner', icon: Bot },
  { to: '/decisions', label: 'Decisions', icon: MessageCircleQuestion, badge: 'decisions' as const },
  { to: '/artifacts', label: 'Artifacts', icon: Package },
  { to: '/knowledge', label: 'Knowledge', icon: BookOpen },
  { to: '/search', label: 'Search', icon: Search },
]

export function AppShell({ onLogout }: { onLogout: () => void }) {
  const navigate = useNavigate()
  const { resolvedTheme, setTheme } = useTheme()
  const [query, setQuery] = useState('')
  const searchRef = useRef<HTMLInputElement>(null)
  const pending = useQuery({
    queryKey: ['decisions', 'pending-count'],
    queryFn: () => api.decisions({ status: 'pending', limit: 1 }),
    refetchInterval: 10_000,
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <aside className="flex w-52 shrink-0 flex-col border-r bg-muted/30">
        <div className="flex h-12 items-center gap-2 border-b px-4 font-semibold tracking-tight">
          <span className="rounded bg-primary px-1.5 py-0.5 font-mono text-xs text-primary-foreground">pm</span>
          ohmypm
        </div>
        <nav className="flex-1 space-y-0.5 p-2">
          {NAV.map(({ to, label, icon: Icon, end, badge }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground',
                  isActive && 'bg-muted font-medium text-foreground',
                )
              }
            >
              <Icon className="size-4" />
              <span className="flex-1">{label}</span>
              {badge === 'decisions' && (pending.data?.total ?? 0) > 0 && (
                <Badge className="h-5 bg-amber-500 px-1.5 text-white">{pending.data?.total}</Badge>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="border-t p-2 text-xs text-muted-foreground">
          <Button variant="ghost" size="sm" className="w-full justify-start" onClick={() => { clearToken(); onLogout() }}>
            <LogOut /> Sign out
          </Button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-3 border-b px-4">
          <form
            className="relative w-full max-w-md"
            onSubmit={(e) => {
              e.preventDefault()
              if (query.trim()) void navigate(`/search?q=${encodeURIComponent(query.trim())}`)
            }}
          >
            <Search className="absolute top-2 left-2.5 size-4 text-muted-foreground" />
            <Input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search tasks, projects, decisions, artifacts…  (Ctrl+K)"
              className="h-8 pl-8"
            />
          </form>
          <div className="ml-auto">
            <Button
              variant="ghost"
              size="icon"
              aria-label="Toggle theme"
              onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
            >
              {resolvedTheme === 'dark' ? <Sun /> : <Moon />}
            </Button>
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-auto">
          <div className="mx-auto max-w-7xl p-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
