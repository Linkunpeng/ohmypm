import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronRight, FileEdit, MessageSquare, Terminal, TriangleAlert, Wrench } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { streamEvents } from '@/lib/sse'
import type { RunEvent } from '@/lib/types'
import { cn } from '@/lib/utils'

const FILTERS: Record<string, (e: RunEvent) => boolean> = {
  all: () => true,
  messages: (e) => e.event_type === 'agent.message' || e.event_type === 'agent.result',
  tools: (e) => e.event_type.startsWith('tool.') || e.event_type === 'file.changed',
  errors: (e) => /error|failed|warning|denied|stderr/.test(e.event_type),
}

function iconFor(type: string) {
  if (type.startsWith('tool.')) return <Wrench className="size-3.5" />
  if (type === 'file.changed') return <FileEdit className="size-3.5" />
  if (type === 'agent.message' || type === 'agent.result') return <MessageSquare className="size-3.5" />
  if (/error|failed|denied|warning/.test(type)) return <TriangleAlert className="size-3.5" />
  return <Terminal className="size-3.5" />
}

function summary(e: RunEvent): string {
  const p = e.payload as Record<string, unknown>
  const str = (v: unknown) => (typeof v === 'string' ? v : v === undefined || v === null ? '' : JSON.stringify(v))
  switch (e.event_type) {
    case 'tool.started':
      return `${str(p.tool)} ${str(p.input)}`
    case 'tool.completed':
      return `${str(p.tool)}${p.is_error ? ' ✗' : ' ✓'} ${str(p.output)}`
    case 'file.changed':
      return str(p.path)
    case 'run.status':
      return `status → ${str(p.status)}${p.error ? `: ${str(p.error)}` : ''}`
    case 'run.claimed':
      return `claimed by runner ${str(p.runner)}`
    case 'agent.started':
      return `${str(p.agent)} started${p.model ? ` (${str(p.model)})` : ''}${p.session_id ? ` session ${str(p.session_id)}` : ''}`
    default:
      return str(p.text ?? p.message ?? p.result ?? p.error ?? p.summary ?? (Object.keys(p).length ? p : ''))
  }
}

const TONE: Record<string, string> = {
  'agent.message': 'text-foreground',
  'agent.result': 'text-emerald-600 dark:text-emerald-400',
  'agent.completed': 'text-emerald-600 dark:text-emerald-400',
  'agent.error': 'text-red-600 dark:text-red-400',
  'agent.failed': 'text-red-600 dark:text-red-400',
  'approval.denied': 'text-amber-600 dark:text-amber-400',
  'agent.warning': 'text-amber-600 dark:text-amber-400',
  'agent.stderr': 'text-muted-foreground',
}

export function RunEventRow({ event }: { event: RunEvent }) {
  const [open, setOpen] = useState(false)
  const text = summary(event)
  return (
    <div className="group border-b border-border/40 py-1 font-mono text-xs last:border-0">
      <button type="button" className="flex w-full items-start gap-2 text-left" onClick={() => setOpen((v) => !v)}>
        <span className="w-10 shrink-0 text-right text-muted-foreground tabular-nums">{event.seq}</span>
        <span className="w-16 shrink-0 text-muted-foreground tabular-nums">
          {new Date(event.timestamp).toLocaleTimeString([], { hour12: false })}
        </span>
        <span className="flex w-48 shrink-0 items-center gap-1 text-sky-700 dark:text-sky-400">
          {iconFor(event.event_type)}
          {event.event_type}
        </span>
        <span className={cn('min-w-0 flex-1 whitespace-pre-wrap break-words', TONE[event.event_type], !open && 'line-clamp-3')}>
          {text}
        </span>
        <ChevronRight className={cn('size-3 shrink-0 opacity-0 transition group-hover:opacity-60', open && 'rotate-90')} />
      </button>
      {open && (
        <pre className="mt-1 ml-28 max-h-80 overflow-auto rounded bg-muted p-2 text-[11px]">
          {JSON.stringify(event.payload, null, 2)}
        </pre>
      )}
    </div>
  )
}

/** Live run log over SSE with replay; closing the page never affects the run. */
export function RunLog({ runId, onEnd }: { runId: string; onEnd?: (status: string) => void }) {
  const [events, setEvents] = useState<RunEvent[]>([])
  const [ended, setEnded] = useState<string | null>(null)
  const [filter, setFilter] = useState<keyof typeof FILTERS>('all')
  const [follow, setFollow] = useState(true)
  const bottom = useRef<HTMLDivElement>(null)
  const onEndRef = useRef(onEnd)
  useEffect(() => {
    onEndRef.current = onEnd
  }, [onEnd])

  // Parents key this component by runId, so state starts fresh for every run.
  useEffect(() => {
    const controller = new AbortController()
    void streamEvents(`/api/runs/${runId}/events`, {
      signal: controller.signal,
      onMessage: (msg) => {
        if (msg.event === 'run_event') {
          const event = JSON.parse(msg.data) as RunEvent
          setEvents((prev) => (prev.some((e) => e.seq === event.seq) ? prev : [...prev, event]))
        } else if (msg.event === 'end') {
          const status = (JSON.parse(msg.data) as { status: string }).status
          setEnded(status)
          onEndRef.current?.(status)
        }
      },
    })
    return () => controller.abort()
  }, [runId])

  useEffect(() => {
    if (follow) bottom.current?.scrollIntoView({ block: 'end' })
  }, [events, follow])

  const shown = useMemo(() => events.filter(FILTERS[filter] ?? FILTERS.all!), [events, filter])

  return (
    <div className="flex min-h-0 flex-col rounded-lg border">
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
        {Object.keys(FILTERS).map((key) => (
          <Badge
            key={key}
            asChild
            variant={filter === key ? 'default' : 'outline'}
            className="cursor-pointer capitalize"
          >
            <button type="button" onClick={() => setFilter(key)}>
              {key}
            </button>
          </Badge>
        ))}
        <span className="ml-auto text-xs text-muted-foreground">
          {events.length} events{ended ? ` · finished (${ended})` : ' · live'}
        </span>
        <div className="flex items-center gap-1.5">
          <Switch id={`follow-${runId}`} checked={follow} onCheckedChange={setFollow} />
          <Label htmlFor={`follow-${runId}`} className="text-xs">
            follow
          </Label>
        </div>
      </div>
      <div className="max-h-[60vh] min-h-48 overflow-auto px-3 py-2" data-testid="run-log">
        {shown.length === 0 ? (
          <div className="py-6 text-center text-sm text-muted-foreground">
            {ended ? 'No events.' : 'Waiting for events…'}
          </div>
        ) : (
          shown.map((e) => <RunEventRow key={e.seq} event={e} />)
        )}
        <div ref={bottom} />
      </div>
    </div>
  )
}
