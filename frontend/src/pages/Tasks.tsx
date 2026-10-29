import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router'

import { EmptyState, ErrorAlert, Loading, PageHeader, StatusBadge } from '@/components/common'
import { CreateTaskDialog } from '@/components/forms'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api } from '@/lib/api'
import { label, timeAgo } from '@/lib/format'
import { TASK_STATUSES, type Task } from '@/lib/types'

export function TaskTable({ tasks }: { tasks: Task[] }) {
  if (tasks.length === 0) return <EmptyState title="No tasks match" />
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-16">Key</TableHead>
          <TableHead>Title</TableHead>
          <TableHead className="w-32">Status</TableHead>
          <TableHead className="w-20">Priority</TableHead>
          <TableHead>Next action</TableHead>
          <TableHead className="w-24 text-right">Updated</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {tasks.map((t) => (
          <TableRow key={t.id}>
            <TableCell className="font-mono text-xs text-muted-foreground">{t.key}</TableCell>
            <TableCell className="max-w-md">
              <Link to={`/tasks/${t.id}`} className="font-medium hover:underline">
                {t.title}
              </Link>
              {!t.project_id && (
                <Badge variant="outline" className="ml-2 text-[10px]">
                  anonymous
                </Badge>
              )}
            </TableCell>
            <TableCell>
              <StatusBadge status={t.status} />
            </TableCell>
            <TableCell>
              <StatusBadge status={t.priority} />
            </TableCell>
            <TableCell className="max-w-xs truncate text-muted-foreground">{t.next_action}</TableCell>
            <TableCell className="text-right text-muted-foreground">{timeAgo(t.updated_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

export function Tasks() {
  const [params, setParams] = useSearchParams()
  const status = params.get('status') ?? 'open'
  const q = params.get('q') ?? ''
  const anonymous = params.get('anonymous') === '1'
  const ready = params.get('ready') === '1'
  const workspaceId = params.get('workspace_id') ?? undefined
  const update = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value === null || value === '') next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: true })
  }
  const statuses = status === 'all' ? undefined : status === 'open' ? ['todo', 'in_progress', 'blocked', 'awaiting_user'] : [status]
  const tasks = useQuery({
    queryKey: ['tasks', status, q, anonymous, ready, workspaceId],
    queryFn: () =>
      api.tasks({ status: statuses, q, anonymous, ready, workspace_id: workspaceId, limit: 200, sort: ready ? 'priority' : '-updated_at' }),
    refetchInterval: 10_000,
  })
  return (
    <div className="space-y-4">
      <PageHeader
        title={anonymous ? 'Anonymous tasks' : 'Tasks'}
        description={anonymous ? 'Tasks not attached to any project.' : 'All tasks across projects.'}
        actions={<CreateTaskDialog />}
      />
      <div className="flex flex-wrap items-center gap-3">
        <Input placeholder="Search…" defaultValue={q} onChange={(e) => update('q', e.target.value)} className="w-64" />
        <Select value={status} onValueChange={(v) => update('status', v)}>
          <SelectTrigger className="w-44" aria-label="Status filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="open">Open</SelectItem>
            <SelectItem value="all">All</SelectItem>
            {TASK_STATUSES.map((s) => (
              <SelectItem key={s} value={s}>
                {label(s)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={ready} onCheckedChange={(v) => update('ready', v ? '1' : null)} /> Ready (deps done)
        </label>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={anonymous} onCheckedChange={(v) => update('anonymous', v ? '1' : null)} /> Anonymous only
        </label>
        {tasks.data && <span className="ml-auto text-sm text-muted-foreground">{tasks.data.total} tasks</span>}
      </div>
      {tasks.isLoading && <Loading />}
      {tasks.error && <ErrorAlert error={tasks.error} />}
      {tasks.data && <TaskTable tasks={tasks.data.items} />}
    </div>
  )
}
