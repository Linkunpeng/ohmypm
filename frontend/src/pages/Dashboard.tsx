import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'

import { EmptyState, ErrorAlert, Loading, PageHeader, StatusBadge, TaskLink } from '@/components/common'
import { DecisionResolver } from '@/components/forms'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { api } from '@/lib/api'
import { duration, shortId, timeAgo } from '@/lib/format'
import type { Run } from '@/lib/types'

function Stat({ label, value, to }: { label: string; value: number | string; to?: string }) {
  const body = (
    <Card className="gap-1 py-4">
      <CardContent className="px-4">
        <div className="text-2xl font-semibold tabular-nums">{value}</div>
        <div className="text-xs text-muted-foreground">{label}</div>
      </CardContent>
    </Card>
  )
  return to ? <Link to={to}>{body}</Link> : body
}

export function RunRow({ run }: { run: Run }) {
  return (
    <Link to={`/runs/${run.id}`} className="flex items-center gap-3 rounded-md px-2 py-1.5 text-sm hover:bg-muted">
      <StatusBadge status={run.status} />
      <span className="font-mono text-xs text-muted-foreground">{shortId(run.id)}</span>
      <span className="font-medium">{run.agent_type}</span>
      <span className="min-w-0 flex-1 truncate text-muted-foreground">{run.error ?? run.result_summary ?? ''}</span>
      <span className="text-xs text-muted-foreground">
        {run.finished_at ? timeAgo(run.finished_at) : duration(run.started_at ?? run.created_at, null)}
      </span>
    </Link>
  )
}

export function Dashboard() {
  const { data, error, isLoading } = useQuery({ queryKey: ['dashboard'], queryFn: api.dashboard, refetchInterval: 5000 })
  if (isLoading) return <Loading />
  if (error || !data) return <ErrorAlert error={error} />
  const s = data.tasks_by_status
  return (
    <div className="space-y-6">
      <PageHeader title="Dashboard" description="What is happening across projects and agents." />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Stat label="Projects" value={data.projects_total} to="/projects" />
        <Stat label="Tasks in progress" value={s.in_progress ?? 0} to="/tasks?status=in_progress" />
        <Stat label="Awaiting you" value={(s.awaiting_user ?? 0) + data.pending_decisions.length} to="/decisions" />
        <Stat label="Todo" value={s.todo ?? 0} to="/tasks?status=todo" />
        <Stat label="Active runs" value={data.active_runs.length} to="/runs" />
        <Stat label="Runners online" value={data.runners_online} to="/runs" />
      </div>

      {data.pending_decisions.length > 0 && (
        <Card className="border-amber-500/50">
          <CardHeader>
            <CardTitle className="text-base">Decisions waiting for you</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            {data.pending_decisions.slice(0, 4).map((d) => (
              <div key={d.id} className="rounded-lg border p-3">
                <div className="mb-1 font-medium">{d.question}</div>
                {d.task_id && (
                  <div className="mb-2 text-xs text-muted-foreground">
                    task <TaskLink id={d.task_id} label={shortId(d.task_id)} />
                  </div>
                )}
                <DecisionResolver decision={d} />
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Agent runs</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {data.active_runs.length === 0 && data.recent_runs.length === 0 && <EmptyState title="No runs yet" />}
            {data.active_runs.map((r) => (
              <RunRow key={r.id} run={r} />
            ))}
            {data.recent_runs
              .filter((r) => !data.active_runs.some((a) => a.id === r.id))
              .map((r) => (
                <RunRow key={r.id} run={r} />
              ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Tasks in progress</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {[...data.tasks_awaiting_user, ...data.tasks_in_progress].length === 0 && (
              <EmptyState title="Nothing in progress" />
            )}
            {[...data.tasks_awaiting_user, ...data.tasks_in_progress].map((t) => (
              <Link key={t.id} to={`/tasks/${t.id}`} className="flex items-center gap-3 rounded-md px-2 py-1.5 text-sm hover:bg-muted">
                <span className="w-12 font-mono text-xs text-muted-foreground">{t.key}</span>
                <span className="min-w-0 flex-1 truncate font-medium">{t.title}</span>
                <StatusBadge status={t.status} />
              </Link>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recent artifacts</CardTitle>
        </CardHeader>
        <CardContent>
          {data.recent_artifacts.length === 0 ? (
            <EmptyState title="No artifacts registered" />
          ) : (
            <div className="grid gap-2 md:grid-cols-2">
              {data.recent_artifacts.map((a) => (
                <Link key={a.id} to={`/artifacts?id=${a.id}`} className="rounded-md border p-2 text-sm hover:bg-muted">
                  <div className="font-medium">
                    {a.name} <span className="text-xs text-muted-foreground">{a.type}</span>
                  </div>
                  <div className="truncate font-mono text-xs text-muted-foreground">{a.storage_uri}</div>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
