import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { BulletList, EmptyState, ErrorAlert, KeyValue, Loading, Mono, PageHeader, StatusBadge } from '@/components/common'
import { CompleteTaskDialog, DecisionResolver, DispatchDialog, RegisterArtifactDialog } from '@/components/forms'
import { RunRow } from '@/pages/Dashboard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { api, errorMessage } from '@/lib/api'
import { dateTime, label, shortId, timeAgo } from '@/lib/format'
import type { Checkpoint, ContextMode, TaskDetail, TaskEvent, TaskStatus } from '@/lib/types'

const MANUAL_STATUSES: TaskStatus[] = ['todo', 'in_progress', 'blocked', 'awaiting_user', 'cancelled']

function CheckpointCard({ cp, task }: { cp: Checkpoint; task: TaskDetail }) {
  return (
    <Card className="gap-3">
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div>
          <CardTitle className="text-sm font-medium whitespace-pre-wrap">{cp.summary}</CardTitle>
          <div className="mt-1 text-xs text-muted-foreground">
            {dateTime(cp.created_at)} · {cp.created_by}
            {cp.run_id && (
              <>
                {' · '}
                <Link className="hover:underline" to={`/runs/${cp.run_id}`}>
                  run {shortId(cp.run_id)}
                </Link>
              </>
            )}
            {cp.auto_generated && (
              <Badge variant="outline" className="ml-2 text-[10px]">
                auto
              </Badge>
            )}
          </div>
        </div>
        <DispatchDialog
          task={task}
          fromCheckpointId={cp.id}
          trigger={
            <Button size="xs" variant="outline">
              Resume from here
            </Button>
          }
        />
      </CardHeader>
      <CardContent className="grid gap-3 text-sm md:grid-cols-2">
        {cp.completed.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground uppercase">Completed</div>
            <BulletList items={cp.completed} />
          </div>
        )}
        {cp.remaining.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground uppercase">Remaining</div>
            <BulletList items={cp.remaining} />
          </div>
        )}
        {cp.current_issue && (cp.current_issue.description || cp.current_issue.error) && (
          <div className="md:col-span-2">
            <div className="mb-1 text-xs font-medium text-muted-foreground uppercase">Current issue</div>
            <KeyValue
              items={[
                ['Description', cp.current_issue.description],
                ['Error', cp.current_issue.error && <Mono key="error">{cp.current_issue.error}</Mono>],
                ['Root cause', cp.current_issue.root_cause],
              ]}
            />
          </div>
        )}
        {cp.attempts.length > 0 && (
          <div className="md:col-span-2">
            <div className="mb-1 text-xs font-medium text-muted-foreground uppercase">Attempts</div>
            <ul className="space-y-1">
              {cp.attempts.map((a, i) => (
                <li key={i}>
                  <span className="font-medium">{a.action}</span> → {a.result}
                  {a.conclusion && <span className="text-muted-foreground"> ({a.conclusion})</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
        {cp.findings.length > 0 && (
          <div className="md:col-span-2">
            <div className="mb-1 text-xs font-medium text-muted-foreground uppercase">Findings</div>
            <ul className="space-y-1">
              {cp.findings.map((f, i) => (
                <li key={i}>
                  <Badge variant="outline" className="mr-2 text-[10px]">
                    {f.kind}
                  </Badge>
                  {f.statement}
                  {f.evidence && <span className="text-muted-foreground"> — {f.evidence}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
        {cp.next_steps.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground uppercase">Next steps</div>
            <BulletList items={cp.next_steps} />
          </div>
        )}
        {cp.verification.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground uppercase">Verification</div>
            {cp.verification.map((v, i) => (
              <div key={i}>
                <Mono>{v.command}</Mono> → {v.result} {v.passed === true ? '✓' : v.passed === false ? '✗' : ''}
              </div>
            ))}
          </div>
        )}
        {cp.relevant_files.length > 0 && (
          <div className="flex flex-wrap gap-1 md:col-span-2">
            {cp.relevant_files.map((f) => (
              <Mono key={f}>{f}</Mono>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function eventText(e: TaskEvent): string {
  const p = e.payload as Record<string, unknown>
  switch (e.event_type) {
    case 'task.status_changed':
      return `${String(p.from)} → ${String(p.to)}${p.note ? ` (${String(p.note)})` : ''}`
    case 'task.updated':
      return `changed ${Object.keys((p.changes as Record<string, unknown>) ?? {}).join(', ')}`
    case 'run.dispatched':
      return `${String(p.agent_type)} run queued`
    case 'run.finished':
      return `run ${String(p.status)}${p.error ? `: ${String(p.error)}` : ''}`
    default:
      return String(p.summary ?? p.question ?? p.title ?? p.name ?? '')
  }
}

function Timeline({ taskId }: { taskId: string }) {
  const events = useQuery({ queryKey: ['task-events', taskId], queryFn: () => api.taskEvents(taskId), refetchInterval: 5000 })
  if (!events.data) return <Loading />
  return (
    <ol className="relative space-y-3 border-l pl-4">
      {[...events.data].reverse().map((e) => (
        <li key={e.id} className="text-sm">
          <span className="absolute -left-1 mt-1.5 size-2 rounded-full bg-muted-foreground/50" />
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="font-mono text-xs text-sky-700 dark:text-sky-400">{e.event_type}</span>
            <span className="min-w-0 flex-1">{eventText(e)}</span>
            <span className="text-xs text-muted-foreground" title={dateTime(e.created_at)}>
              {e.actor} · {timeAgo(e.created_at)}
            </span>
          </div>
        </li>
      ))}
    </ol>
  )
}

function ContextPreview({ taskId }: { taskId: string }) {
  const [mode, setMode] = useState<ContextMode>('standard')
  const ctx = useQuery({ queryKey: ['context', taskId, mode], queryFn: () => api.taskContext(taskId, mode) })
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 text-sm">
        <Select value={mode} onValueChange={(v) => setMode(v as ContextMode)}>
          <SelectTrigger className="w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="brief">brief</SelectItem>
            <SelectItem value="standard">standard</SelectItem>
            <SelectItem value="full">full</SelectItem>
          </SelectContent>
        </Select>
        {ctx.data && (
          <span className="text-muted-foreground">
            ~{ctx.data.estimated_tokens} tokens · sections: {ctx.data.sections.join(', ')}
            {ctx.data.truncated && ' · truncated'}
          </span>
        )}
      </div>
      <pre className="max-h-[60vh] overflow-auto rounded-lg border bg-muted/40 p-4 text-xs whitespace-pre-wrap">
        {ctx.data?.markdown ?? 'Loading…'}
      </pre>
    </div>
  )
}

export function TaskView() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const task = useQuery({ queryKey: ['task', id], queryFn: () => api.task(id), refetchInterval: 5000 })
  const taskId = task.data?.id ?? ''
  const checkpoints = useQuery({ queryKey: ['checkpoints', taskId], queryFn: () => api.checkpoints(taskId), enabled: !!taskId })
  const decisions = useQuery({ queryKey: ['decisions', 'task', taskId], queryFn: () => api.decisions({ task_id: taskId }), enabled: !!taskId })
  const artifacts = useQuery({ queryKey: ['artifacts', 'task', taskId], queryFn: () => api.artifacts({ task_id: taskId }), enabled: !!taskId })
  const runs = useQuery({ queryKey: ['runs', 'task', taskId], queryFn: () => api.runs({ task_id: taskId, limit: 50 }), enabled: !!taskId, refetchInterval: 3000 })
  const sessions = useQuery({ queryKey: ['sessions', taskId], queryFn: () => api.sessions(taskId), enabled: !!taskId })
  const [editing, setEditing] = useState(false)
  const [description, setDescription] = useState('')

  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.updateTask(taskId, { ...body, expected_version: task.data?.version }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['task', id] })
      void qc.invalidateQueries({ queryKey: ['task-events', taskId] })
      setEditing(false)
    },
    onError: (err) => toast.error(errorMessage(err)),
  })

  if (task.isLoading) return <Loading />
  if (task.error || !task.data) return <ErrorAlert error={task.error} />
  const t = task.data
  const lastRun = runs.data?.items[0]
  const closed = t.status === 'completed' || t.status === 'cancelled'

  return (
    <div className="space-y-5">
      <PageHeader
        title={
          <span>
            <span className="mr-2 font-mono text-base text-muted-foreground">{t.key}</span>
            {t.title}
          </span>
        }
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge status={t.status} />
            <StatusBadge status={t.priority} />
            {t.project_id ? (
              <Link to={`/projects/${t.project_id}`} className="hover:underline">
                project {shortId(t.project_id)}
              </Link>
            ) : (
              <Badge variant="outline">anonymous</Badge>
            )}
            <span>updated {timeAgo(t.updated_at)}</span>
          </span>
        }
        actions={
          <>
            <Select value={t.status} onValueChange={(v) => update.mutate({ status: v })}>
              <SelectTrigger className="h-8 w-40" aria-label="Task status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MANUAL_STATUSES.map((s) => (
                  <SelectItem key={s} value={s}>
                    {label(s)}
                  </SelectItem>
                ))}
                {t.status === 'completed' && <SelectItem value="completed">completed</SelectItem>}
              </SelectContent>
            </Select>
            {!closed && <CompleteTaskDialog task={t} />}
            {lastRun && !closed && (
              <DispatchDialog
                task={t}
                defaultAgent={lastRun.agent_type === 'claude' ? 'codex' : 'claude'}
                trigger={
                  <Button size="sm" variant="outline">
                    Hand off to another agent
                  </Button>
                }
              />
            )}
            {!closed && <DispatchDialog task={t} defaultAgent={lastRun?.agent_type} />}
          </>
        }
      />

      {t.unmet_dependencies.length > 0 && (
        <div className="rounded-md border border-orange-500/40 bg-orange-500/5 p-3 text-sm">
          Waiting on dependencies:{' '}
          {t.unmet_dependencies.map((d) => (
            <Link key={d} to={`/tasks/${d}`} className="mr-2 font-mono hover:underline">
              {shortId(d)}
            </Link>
          ))}
        </div>
      )}

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="checkpoints">Checkpoints ({checkpoints.data?.total ?? 0})</TabsTrigger>
          <TabsTrigger value="runs">Runs ({runs.data?.total ?? 0})</TabsTrigger>
          <TabsTrigger value="decisions">Decisions ({decisions.data?.total ?? 0})</TabsTrigger>
          <TabsTrigger value="artifacts">Artifacts ({artifacts.data?.total ?? 0})</TabsTrigger>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="context">Agent context</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-4 lg:col-span-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Original request</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm whitespace-pre-wrap">{t.raw_request}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle className="text-sm">Structured description</CardTitle>
                {!editing && (
                  <Button size="xs" variant="ghost" onClick={() => { setDescription(t.description); setEditing(true) }}>
                    Edit
                  </Button>
                )}
              </CardHeader>
              <CardContent>
                {editing ? (
                  <div className="space-y-2">
                    <Textarea rows={8} value={description} onChange={(e) => setDescription(e.target.value)} />
                    <div className="flex gap-2">
                      <Button size="sm" onClick={() => update.mutate({ description })}>
                        Save
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm whitespace-pre-wrap text-muted-foreground">
                    {t.description || 'No structured description yet (agents usually add one).'}
                  </p>
                )}
              </CardContent>
            </Card>
            <div className="grid gap-4 md:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">Done</CardTitle>
                </CardHeader>
                <CardContent>
                  <BulletList items={t.completed_items} empty="Nothing recorded yet" />
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">Remaining</CardTitle>
                </CardHeader>
                <CardContent>
                  <BulletList items={t.remaining_items} empty="Nothing recorded" />
                </CardContent>
              </Card>
            </div>
          </div>
          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Next action</CardTitle>
              </CardHeader>
              <CardContent className="text-sm">{t.next_action || <span className="text-muted-foreground">—</span>}</CardContent>
            </Card>
            {t.blockers.length > 0 && (
              <Card className="border-orange-500/40">
                <CardHeader>
                  <CardTitle className="text-sm">Blockers</CardTitle>
                </CardHeader>
                <CardContent>
                  <BulletList items={t.blockers} />
                </CardContent>
              </Card>
            )}
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Acceptance criteria</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <BulletList items={t.acceptance_criteria} empty="None defined" />
                {t.acceptance_result && (
                  <div className="rounded-md bg-emerald-500/10 p-2 text-xs">
                    <div className="font-medium">Verified by {String(t.acceptance_result.verified_by)}</div>
                    <div className="whitespace-pre-wrap">{String(t.acceptance_result.summary ?? '')}</div>
                  </div>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Agent sessions</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-sm">
                {sessions.data?.length === 0 && <div className="text-muted-foreground">None yet</div>}
                {sessions.data?.map((s) => (
                  <div key={s.id} className="flex justify-between gap-2">
                    <span>
                      {s.agent_type} <span className="font-mono text-xs text-muted-foreground">{shortId(s.id)}</span>
                    </span>
                    <span className="truncate font-mono text-xs text-muted-foreground">{s.native_session_id ?? ''}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-0">
                <KeyValue
                  items={[
                    ['Task ID', <Mono key="id">{t.id}</Mono>],
                    ['Created', `${dateTime(t.created_at)} by ${t.created_by ?? '?'}`],
                    ['Completed', dateTime(t.completed_at)],
                    ['Version', t.version],
                  ]}
                />
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="checkpoints" className="space-y-3">
          {checkpoints.data?.items.length === 0 && <EmptyState title="No checkpoints yet" />}
          {checkpoints.data?.items.map((cp) => <CheckpointCard key={cp.id} cp={cp} task={t} />)}
        </TabsContent>

        <TabsContent value="runs" className="space-y-1">
          {runs.data?.items.length === 0 && <EmptyState title="No runs yet">Assign an agent with “Run agent”.</EmptyState>}
          {runs.data?.items.map((r) => <RunRow key={r.id} run={r} />)}
        </TabsContent>

        <TabsContent value="decisions" className="space-y-3">
          {decisions.data?.items.length === 0 && <EmptyState title="No decisions" />}
          {decisions.data?.items.map((d) => (
            <Card key={d.id}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <StatusBadge status={d.status} /> {d.question}
                </CardTitle>
                {d.context && <p className="text-sm whitespace-pre-wrap text-muted-foreground">{d.context}</p>}
                {d.reasoning && <p className="text-xs text-muted-foreground">Agent reasoning: {d.reasoning}</p>}
              </CardHeader>
              <CardContent>
                <DecisionResolver decision={d} />
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="artifacts" className="space-y-2">
          <div className="flex justify-end">
            <RegisterArtifactDialog taskId={t.id} projectId={t.project_id ?? undefined} />
          </div>
          {artifacts.data?.items.length === 0 && <EmptyState title="No artifacts" />}
          {artifacts.data?.items.map((a) => (
            <Link key={a.id} to={`/artifacts?id=${a.id}`} className="block rounded-md border p-3 text-sm hover:bg-muted">
              <div className="font-medium">
                {a.name} <span className="text-xs text-muted-foreground">{a.type}</span>
              </div>
              <div className="font-mono text-xs text-muted-foreground">{a.storage_uri}</div>
            </Link>
          ))}
        </TabsContent>

        <TabsContent value="timeline">
          <Timeline taskId={t.id} />
        </TabsContent>

        <TabsContent value="context">
          <ContextPreview taskId={t.id} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
