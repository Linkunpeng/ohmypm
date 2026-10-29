import type { ReactNode } from 'react'
import { AlertCircle, Inbox, Loader2 } from 'lucide-react'
import { Link } from 'react-router'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { errorMessage } from '@/lib/api'
import { label } from '@/lib/format'
import { cn } from '@/lib/utils'

const STATUS_STYLES: Record<string, string> = {
  todo: 'bg-slate-500/15 text-slate-700 dark:text-slate-300',
  in_progress: 'bg-blue-500/15 text-blue-700 dark:text-blue-300',
  blocked: 'bg-orange-500/15 text-orange-700 dark:text-orange-300',
  awaiting_user: 'bg-amber-500/20 text-amber-800 dark:text-amber-300',
  completed: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  cancelled: 'bg-zinc-500/15 text-zinc-500 line-through',
  queued: 'bg-slate-500/15 text-slate-700 dark:text-slate-300',
  starting: 'bg-sky-500/15 text-sky-700 dark:text-sky-300',
  running: 'bg-blue-500/15 text-blue-700 dark:text-blue-300',
  waiting_approval: 'bg-amber-500/20 text-amber-800 dark:text-amber-300',
  failed: 'bg-red-500/15 text-red-700 dark:text-red-300',
  interrupted: 'bg-orange-500/15 text-orange-700 dark:text-orange-300',
  lost: 'bg-red-500/15 text-red-700 dark:text-red-300',
  pending: 'bg-amber-500/20 text-amber-800 dark:text-amber-300',
  resolved: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  passed: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  unknown: 'bg-slate-500/15 text-slate-600 dark:text-slate-300',
  urgent: 'bg-red-500/15 text-red-700 dark:text-red-300',
  high: 'bg-orange-500/15 text-orange-700 dark:text-orange-300',
  normal: 'bg-slate-500/10 text-slate-600 dark:text-slate-400',
  low: 'bg-slate-500/5 text-slate-500',
}

const LIVE = new Set(['running', 'starting'])

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <Badge variant="secondary" className={cn('gap-1 font-medium capitalize', STATUS_STYLES[status], className)}>
      {LIVE.has(status) && <span className="size-1.5 animate-pulse rounded-full bg-current" />}
      {label(status)}
    </Badge>
  )
}

export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="truncate text-xl font-semibold tracking-tight">{title}</h1>
        {description && <div className="mt-1 text-sm text-muted-foreground">{description}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
      <Inbox className="size-5" />
      <div className="font-medium text-foreground">{title}</div>
      {children}
    </div>
  )
}

export function Loading({ label: text = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> {text}
    </div>
  )
}

export function ErrorAlert({ error, title = 'Something went wrong' }: { error: unknown; title?: string }) {
  return (
    <Alert variant="destructive">
      <AlertCircle />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{errorMessage(error)}</AlertDescription>
    </Alert>
  )
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <code className={cn('rounded bg-muted px-1 py-0.5 font-mono text-xs break-all', className)}>{children}</code>

}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="min-w-0 break-words">{v ?? '—'}</dd>
        </div>
      ))}
    </dl>
  )
}

export function BulletList({ items, empty = '—' }: { items: string[]; empty?: string }) {
  if (!items.length) return <div className="text-sm text-muted-foreground">{empty}</div>
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm">
      {items.map((item, i) => (
        <li key={`${i}-${item}`}>{item}</li>
      ))}
    </ul>
  )
}

export function TaskLink({ id, label: text }: { id: string; label: ReactNode }) {
  return (
    <Link to={`/tasks/${id}`} className="font-medium hover:underline">
      {text}
    </Link>
  )
}
