import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { BulletList, EmptyState, ErrorAlert, KeyValue, Loading, Mono, PageHeader, StatusBadge, TaskLink } from '@/components/common'
import { DecisionResolver, KnowledgeDialog, RegisterArtifactDialog } from '@/components/forms'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, errorMessage } from '@/lib/api'
import { dateTime, shortId, timeAgo } from '@/lib/format'
import { ARTIFACT_TYPES } from '@/lib/types'

// ---------------------------------------------------------------- decisions

export function Decisions() {
  const [status, setStatus] = useState('pending')
  const decisions = useQuery({
    queryKey: ['decisions', status],
    queryFn: () => api.decisions(status === 'all' ? { limit: 100 } : { status, limit: 100 }),
    refetchInterval: 5000,
  })
  return (
    <div className="space-y-4">
      <PageHeader
        title="Decisions"
        description="Questions agents could not answer on their own. Blocking decisions pause their task."
        actions={
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="pending">pending</SelectItem>
              <SelectItem value="resolved">resolved</SelectItem>
              <SelectItem value="cancelled">cancelled</SelectItem>
              <SelectItem value="all">all</SelectItem>
            </SelectContent>
          </Select>
        }
      />
      {decisions.isLoading && <Loading />}
      {decisions.error && <ErrorAlert error={decisions.error} />}
      {decisions.data?.items.length === 0 && <EmptyState title="Nothing waiting for you" />}
      <div className="grid gap-4 lg:grid-cols-2">
        {decisions.data?.items.map((d) => (
          <Card key={d.id}>
            <CardHeader>
              <CardTitle className="flex items-start gap-2 text-sm">
                <StatusBadge status={d.status} />
                <span className="flex-1">{d.question}</span>
                {d.blocking && <Badge variant="outline">blocking</Badge>}
              </CardTitle>
              <div className="text-xs text-muted-foreground">
                {d.task_id && (
                  <>
                    task <TaskLink id={d.task_id} label={shortId(d.task_id)} /> ·{' '}
                  </>
                )}
                asked by {d.created_by} {timeAgo(d.created_at)}
              </div>
              {d.context && <p className="text-sm whitespace-pre-wrap text-muted-foreground">{d.context}</p>}
              {d.reasoning && <p className="text-xs text-muted-foreground">Reasoning: {d.reasoning}</p>}
            </CardHeader>
            <CardContent>
              <DecisionResolver decision={d} />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- artifacts

function ArtifactSheet({ id, onClose }: { id: string; onClose: () => void }) {
  const qc = useQueryClient()
  const artifact = useQuery({ queryKey: ['artifact', id], queryFn: () => api.artifact(id) })
  const verify = useMutation({
    mutationFn: (status: 'passed' | 'failed') =>
      api.updateArtifact(id, {
        verification: { ...(artifact.data?.verification ?? {}), status, checked_at: new Date().toISOString() },
        expected_version: artifact.data?.version,
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['artifact', id] }),
    onError: (err) => toast.error(errorMessage(err)),
  })
  const a = artifact.data
  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-auto sm:max-w-xl">
        {!a ? (
          <Loading />
        ) : (
          <>
            <SheetHeader>
              <SheetTitle>{a.name}</SheetTitle>
              <SheetDescription>
                {a.type} · {a.storage_mode} · v{a.version_label ?? '—'}
              </SheetDescription>
            </SheetHeader>
            <div className="space-y-5 px-4 pb-6 text-sm">
              <KeyValue
                items={[
                  ['Location', <Mono key="l">{a.storage_uri}</Mono>],
                  ['SHA-256', a.sha256 ? <Mono key="s">{a.sha256}</Mono> : '—'],
                  ['Task', a.task_id ? <TaskLink key="t" id={a.task_id} label={shortId(a.task_id)} /> : '—'],
                  ['Registered', `${dateTime(a.created_at)} by ${a.created_by ?? '?'}`],
                ]}
              />
              {a.description && <p className="whitespace-pre-wrap">{a.description}</p>}
              <section>
                <h3 className="mb-1 font-medium">Usage</h3>
                {a.usage.command && <Mono>{a.usage.command}</Mono>}
                {a.usage.expected_result && <p className="mt-1 text-muted-foreground">Expected: {a.usage.expected_result}</p>}
                {a.usage.prerequisites && a.usage.prerequisites.length > 0 && (
                  <div className="mt-1">
                    Prerequisites: <BulletList items={a.usage.prerequisites} />
                  </div>
                )}
                {a.usage.manual && <pre className="mt-2 rounded bg-muted p-2 text-xs whitespace-pre-wrap">{a.usage.manual}</pre>}
              </section>
              <section>
                <h3 className="mb-1 font-medium">Build</h3>
                {a.build.command ? <Mono>{a.build.command}</Mono> : <span className="text-muted-foreground">—</span>}
                {a.build.source_path && <div className="mt-1 text-muted-foreground">source: {a.build.source_path}</div>}
              </section>
              {Object.keys(a.environment).length > 0 && (
                <section>
                  <h3 className="mb-1 font-medium">Environment</h3>
                  <pre className="rounded bg-muted p-2 text-xs">{JSON.stringify(a.environment, null, 2)}</pre>
                </section>
              )}
              <section>
                <h3 className="mb-1 font-medium">Verification</h3>
                <div className="flex items-center gap-2">
                  <StatusBadge status={a.verification.status ?? 'unknown'} />
                  {a.verification.command && <Mono>{a.verification.command}</Mono>}
                  <span className="ml-auto flex gap-1">
                    <Button size="xs" variant="outline" onClick={() => verify.mutate('passed')}>
                      Mark passed
                    </Button>
                    <Button size="xs" variant="outline" onClick={() => verify.mutate('failed')}>
                      Mark failed
                    </Button>
                  </span>
                </div>
                {a.verification.result && <p className="mt-1 text-muted-foreground">{a.verification.result}</p>}
              </section>
              <section>
                <h3 className="mb-1 font-medium">Versions</h3>
                {a.versions.map((v) => (
                  <div key={v.id} className="flex gap-2 text-xs">
                    <span className="w-16 font-medium">{v.version_label ?? '—'}</span>
                    <span className="truncate font-mono text-muted-foreground">{v.storage_uri}</span>
                    <span className="ml-auto text-muted-foreground">{timeAgo(v.created_at)}</span>
                  </div>
                ))}
              </section>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

export function Artifacts() {
  const [params, setParams] = useSearchParams()
  const [q, setQ] = useState('')
  const [type, setType] = useState('all')
  const artifacts = useQuery({
    queryKey: ['artifacts', q, type],
    queryFn: () => api.artifacts({ q, type: type === 'all' ? undefined : type, limit: 200 }),
  })
  const selected = params.get('id')
  return (
    <div className="space-y-4">
      <PageHeader title="Artifact registry" description="Deliverables produced by tasks, with how to build, use and verify them." actions={<RegisterArtifactDialog />} />
      <div className="flex gap-3">
        <Input placeholder="Search name, path, description…" value={q} onChange={(e) => setQ(e.target.value)} className="w-72" />
        <Select value={type} onValueChange={setType}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">all types</SelectItem>
            {ARTIFACT_TYPES.map((t) => (
              <SelectItem key={t} value={t}>
                {t}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {artifacts.isLoading && <Loading />}
      {artifacts.data?.items.length === 0 && <EmptyState title="No artifacts" />}
      {artifacts.data && artifacts.data.items.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Location</TableHead>
              <TableHead>Usage</TableHead>
              <TableHead>Verification</TableHead>
              <TableHead>Task</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {artifacts.data.items.map((a) => (
              <TableRow key={a.id} className="cursor-pointer" onClick={() => setParams({ id: a.id })}>
                <TableCell className="font-medium">
                  {a.name} {a.version_label && <span className="text-xs text-muted-foreground">v{a.version_label}</span>}
                </TableCell>
                <TableCell>{a.type}</TableCell>
                <TableCell className="max-w-xs truncate font-mono text-xs">{a.storage_uri}</TableCell>
                <TableCell className="max-w-xs truncate font-mono text-xs">{a.usage.command}</TableCell>
                <TableCell>
                  <StatusBadge status={a.verification.status ?? 'unknown'} />
                </TableCell>
                <TableCell onClick={(e) => e.stopPropagation()}>
                  {a.task_id && <TaskLink id={a.task_id} label={shortId(a.task_id)} />}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {selected && <ArtifactSheet id={selected} onClose={() => setParams({})} />}
    </div>
  )
}

// ---------------------------------------------------------------- knowledge

export function KnowledgePage() {
  const [q, setQ] = useState('')
  const [superseded, setSuperseded] = useState(false)
  const qc = useQueryClient()
  const knowledge = useQuery({
    queryKey: ['knowledge', q, superseded],
    queryFn: () => api.knowledge({ q, include_superseded: superseded, limit: 200 }),
  })
  const toggleVerified = useMutation({
    mutationFn: ({ id, verified, version }: { id: string; verified: boolean; version: number }) =>
      api.updateKnowledge(id, { verified, expected_version: version }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['knowledge'] }),
    onError: (err) => toast.error(errorMessage(err)),
  })
  return (
    <div className="space-y-4">
      <PageHeader title="Project knowledge" description="Long-lived facts and lessons that agents receive as context." actions={<KnowledgeDialog />} />
      <div className="flex items-center gap-3">
        <Input placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} className="w-72" />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={superseded} onChange={(e) => setSuperseded(e.target.checked)} /> include superseded
        </label>
      </div>
      {knowledge.data?.items.length === 0 && <EmptyState title="No knowledge recorded" />}
      <div className="grid gap-3 md:grid-cols-2">
        {knowledge.data?.items.map((k) => (
          <Card key={k.id} className={k.superseded_by ? 'opacity-60' : ''}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm">
                <span className="flex-1">{k.title}</span>
                <Badge variant="outline">{k.category}</Badge>
                <Badge
                  asChild
                  variant={k.verified ? 'default' : 'secondary'}
                  className="cursor-pointer"
                >
                  <button type="button" onClick={() => toggleVerified.mutate({ id: k.id, verified: !k.verified, version: k.version })}>
                    {k.verified ? 'verified' : 'unverified'}
                  </button>
                </Badge>
              </CardTitle>
              <div className="text-xs text-muted-foreground">
                {k.project_id ? (
                  <Link to={`/projects/${k.project_id}`} className="hover:underline">
                    project {shortId(k.project_id)}
                  </Link>
                ) : (
                  'global'
                )}{' '}
                · {k.created_by} · {timeAgo(k.updated_at)}
                {k.superseded_by && ` · superseded by ${shortId(k.superseded_by)}`}
              </div>
            </CardHeader>
            <CardContent className="text-sm whitespace-pre-wrap">{k.content}</CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- search

const KIND_LINK: Record<string, (id: string) => string> = {
  project: (id) => `/projects/${id}`,
  task: (id) => `/tasks/${id}`,
  decision: () => `/decisions`,
  artifact: (id) => `/artifacts?id=${id}`,
  knowledge: () => `/knowledge`,
  workspace: (id) => `/tasks?workspace_id=${id}&status=all`,
}

export function SearchPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const results = useQuery({ queryKey: ['search', q], queryFn: () => api.search(q), enabled: q.trim().length > 0 })
  return (
    <div className="space-y-4">
      <PageHeader title="Search" description="Projects, directories, tasks, decisions, artifacts and knowledge." />
      <form
        onSubmit={(e) => {
          e.preventDefault()
          const value = new FormData(e.currentTarget).get('q')
          setParams({ q: String(value ?? '') })
        }}
      >
        <Input name="q" defaultValue={q} placeholder="Search…" className="max-w-xl" autoFocus />
      </form>
      {results.isLoading && <Loading />}
      {results.error && <ErrorAlert error={results.error} />}
      {results.data?.hits.length === 0 && <EmptyState title={`No results for “${q}”`} />}
      <div className="space-y-2">
        {results.data?.hits.map((h) => (
          <Link
            key={`${h.kind}-${h.id}`}
            to={(KIND_LINK[h.kind] ?? (() => '/'))(h.id)}
            className="block rounded-md border p-3 hover:bg-muted"
          >
            <div className="flex items-center gap-2 text-sm">
              <Badge variant="outline">{h.kind}</Badge>
              <span className="font-medium">{h.title}</span>
              {h.status && <StatusBadge status={h.status} />}
            </div>
            {h.snippet && <div className="mt-1 line-clamp-2 text-sm text-muted-foreground">{h.snippet}</div>}
          </Link>
        ))}
      </div>
    </div>
  )
}
