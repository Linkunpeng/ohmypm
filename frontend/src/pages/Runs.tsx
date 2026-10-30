import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { EmptyState, ErrorAlert, KeyValue, Loading, Mono, PageHeader, StatusBadge } from '@/components/common'
import { DispatchDialog, ProfileDialog } from '@/components/forms'
import { RunLog } from '@/components/RunLog'
import { RunRow } from '@/pages/Dashboard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, errorMessage } from '@/lib/api'
import { dateTime, duration, shortId, timeAgo } from '@/lib/format'
import { ACTIVE_RUN_STATUSES, type Task } from '@/lib/types'

function TaskPicker() {
  const [q, setQ] = useState('')
  const tasks = useQuery({
    queryKey: ['tasks', 'picker', q],
    queryFn: () => api.tasks({ q, status: ['todo', 'in_progress', 'blocked', 'awaiting_user'], limit: 8 }),
  })
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Start a run</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <Input placeholder="Find an open task…" value={q} onChange={(e) => setQ(e.target.value)} />
        {tasks.data?.items.length === 0 && <div className="text-sm text-muted-foreground">No open tasks match.</div>}
        {tasks.data?.items.map((t: Task) => (
          <div key={t.id} className="flex items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-muted">
            <span className="w-12 font-mono text-xs text-muted-foreground">{t.key}</span>
            <Link to={`/tasks/${t.id}`} className="min-w-0 flex-1 truncate hover:underline">
              {t.title}
            </Link>
            <StatusBadge status={t.status} />
            <DispatchDialog
              task={t}
              trigger={
                <Button size="xs" variant="outline">
                  Run…
                </Button>
              }
            />
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

export function Runs() {
  const qc = useQueryClient()
  const runners = useQuery({ queryKey: ['runners'], queryFn: api.runners, refetchInterval: 5000 })
  const agents = useQuery({ queryKey: ['agents'], queryFn: api.agents, refetchInterval: 15_000 })
  const profiles = useQuery({ queryKey: ['profiles'], queryFn: api.profiles })
  const active = useQuery({ queryKey: ['runs', 'active'], queryFn: () => api.runs({ status: ACTIVE_RUN_STATUSES, limit: 50 }), refetchInterval: 2000 })
  const recent = useQuery({ queryKey: ['runs', 'recent'], queryFn: () => api.runs({ active: false, limit: 25 }), refetchInterval: 5000 })
  const deleteProfile = useMutation({
    mutationFn: api.deleteProfile,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['profiles'] }),
    onError: (err) => toast.error(errorMessage(err)),
  })

  return (
    <div className="space-y-6">
      <PageHeader title="Agent Runner" description="Runners on your machines execute agent CLIs for queued runs." />
      <div className="grid gap-4 lg:grid-cols-2">
        <TaskPicker />
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Runners</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {runners.data?.length === 0 && (
              <EmptyState title="No runner registered">
                On the machine with your workspaces run <Mono>ohmypm runner start --allowed-root ~/workspace</Mono>
              </EmptyState>
            )}
            {runners.data?.map((r) => (
              <div key={r.id} className="rounded-md border p-3 text-sm">
                <div className="flex items-center gap-2">
                  <span className={`size-2 rounded-full ${r.online ? 'bg-emerald-500' : 'bg-zinc-400'}`} />
                  <span className="font-medium">{r.name}</span>
                  <span className="text-muted-foreground">@{r.host_id}</span>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {r.active_runs}/{r.max_parallel} active · heartbeat {timeAgo(r.last_heartbeat_at)}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {r.agents.map((a) => (
                    <Badge
                      key={a.agent_type}
                      variant={a.available ? 'secondary' : 'outline'}
                      title={a.detail ?? a.version ?? ''}
                      className={a.available ? '' : 'text-muted-foreground line-through'}
                    >
                      {a.agent_type}
                    </Badge>
                  ))}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">roots: {r.allowed_roots.join(', ') || '—'}</div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Active runs</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          {active.data?.items.length === 0 && <div className="text-sm text-muted-foreground">No queued or running agents.</div>}
          {active.data?.items.map((r) => <RunRow key={r.id} run={r} />)}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Agent CLIs</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Agent</TableHead>
                  <TableHead>Availability</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {agents.data?.map((a) => (
                  <TableRow key={a.agent_type}>
                    <TableCell className="font-medium">{a.display_name ?? a.agent_type}</TableCell>
                    <TableCell className="text-xs">
                      {a.available_on.length === 0 && <span className="text-muted-foreground">no runner reported it</span>}
                      {a.available_on.map((p) => (
                        <div key={p.runner_id} className={p.available ? '' : 'text-muted-foreground'}>
                          {p.runner}: {p.available ? `✓ ${p.version ?? ''}` : `✗ ${p.detail ?? ''}`}
                          {!p.online && ' (offline)'}
                        </div>
                      ))}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">Agents</CardTitle>
            <ProfileDialog />
          </CardHeader>
          <CardContent className="space-y-2">
            {profiles.data?.length === 0 && <div className="text-sm text-muted-foreground">No profiles; agents run with safe defaults.</div>}
            {profiles.data?.map((p) => (
              <div key={p.id} className="flex items-start gap-2 rounded-md border p-2 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="font-medium">
                    {p.name} <span className="text-muted-foreground">({p.agent_type})</span>
                    {p.is_default && <Badge className="ml-2">default</Badge>}
                    {!p.write_mode && <Badge variant="outline" className="ml-2">read-only</Badge>}
                  </div>
                  {p.description && <p className="mt-1 text-muted-foreground">{p.description}</p>}
                  <pre className="mt-1 overflow-auto text-xs text-muted-foreground">{JSON.stringify(p.options)}</pre>
                </div>
                <ProfileDialog key={`${p.id}-${p.version}`} profile={p} />
                <Button size="xs" variant="ghost" disabled={deleteProfile.isPending} onClick={() => { if (window.confirm(`Delete agent ${p.name}?`)) deleteProfile.mutate(p.id) }}>
                  Delete
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recent history</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          {recent.data?.items.map((r) => <RunRow key={r.id} run={r} />)}
        </CardContent>
      </Card>
    </div>
  )
}

export function RunView() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const run = useQuery({ queryKey: ['run', id], queryFn: () => api.run(id), refetchInterval: 2000 })
  const task = useQuery({ queryKey: ['task', run.data?.task_id], queryFn: () => api.task(run.data!.task_id), enabled: !!run.data })
  const cancel = useMutation({
    mutationFn: () => api.cancelRun(id, 'cancelled from web'),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['run', id] })
      toast.info('Cancellation requested')
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
  if (run.isLoading) return <Loading />
  if (run.error || !run.data) return <ErrorAlert error={run.error} />
  const r = run.data
  const isActive = ACTIVE_RUN_STATUSES.includes(r.status)
  return (
    <div className="space-y-4">
      <PageHeader
        title={
          <span className="flex items-center gap-3">
            {r.agent_type} run <span className="font-mono text-base text-muted-foreground">{shortId(r.id)}</span>
            <StatusBadge status={r.status} />
          </span>
        }
        description={
          task.data && (
            <Link to={`/tasks/${task.data.id}`} className="hover:underline">
              {task.data.key} · {task.data.title}
            </Link>
          )
        }
        actions={
          <>
            {isActive && (
              <Button variant="destructive" size="sm" disabled={!!r.cancel_requested_at || cancel.isPending} onClick={() => cancel.mutate()}>
                {r.cancel_requested_at ? 'Cancelling…' : 'Cancel run'}
              </Button>
            )}
            {!isActive && task.data && task.data.status !== 'completed' && task.data.status !== 'cancelled' && (
              <>
                <DispatchDialog
                  task={task.data}
                  defaultAgent={r.agent_type === 'claude' ? 'codex' : 'claude'}
                  trigger={
                    <Button size="sm" variant="outline">
                      Hand off to another agent
                    </Button>
                  }
                />
                <DispatchDialog
                  task={task.data}
                  defaultAgent={r.agent_type}
                  continueRun={r}
                  trigger={<Button size="sm">Continue with {r.agent_type}</Button>}
                />
              </>
            )}
          </>
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <RunLog key={r.id} runId={r.id} onEnd={() => void qc.invalidateQueries({ queryKey: ['run', id] })} />
        </div>
        <div className="space-y-4">
          <Card>
            <CardContent className="pt-0">
              <KeyValue
                items={[
                  ['Status', <StatusBadge key="s" status={r.status} />],
                  ['Profile', r.profile_snapshot.name],
                  ['Mode', `${r.write_mode ? 'write' : 'read-only'} · context ${r.context_mode}`],
                  ['Queued', dateTime(r.created_at)],
                  ['Started', dateTime(r.started_at)],
                  ['Duration', duration(r.started_at, r.finished_at)],
                  ['Exit code', r.exit_code ?? '—'],
                  ['PID', r.pid ?? '—'],
                  ['Native session', r.native_session_id ? <Mono key="n">{r.native_session_id}</Mono> : '—'],
                  ['Session mode', r.resume_native ? 'Native resume requested' : 'New session'],
                  ['Timeout', `${r.timeout_seconds}s`],
                ]}
              />
            </CardContent>
          </Card>
          {r.error && (
            <Card className="border-red-500/40">
              <CardHeader>
                <CardTitle className="text-sm">Error {r.error_code && <Mono>{r.error_code}</Mono>}</CardTitle>
              </CardHeader>
              <CardContent className="text-sm whitespace-pre-wrap">{r.error}</CardContent>
            </Card>
          )}
          {r.result_summary && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Agent's final message</CardTitle>
              </CardHeader>
              <CardContent className="max-h-80 overflow-auto text-sm whitespace-pre-wrap">{r.result_summary}</CardContent>
            </Card>
          )}
          {Object.keys(r.usage).length > 0 && (
            <Card>
              <CardHeader><CardTitle className="text-sm">Provider usage</CardTitle></CardHeader>
              <CardContent><pre className="overflow-auto text-xs">{JSON.stringify(r.usage, null, 2)}</pre></CardContent>
            </Card>
          )}
          {r.instructions && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Instructions</CardTitle>
              </CardHeader>
              <CardContent className="text-sm whitespace-pre-wrap">{r.instructions}</CardContent>
            </Card>
          )}
          {r.command.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Command</CardTitle>
              </CardHeader>
              <CardContent>
                <Mono>{r.command.join(' ')}</Mono>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
