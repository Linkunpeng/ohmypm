import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'

import { EmptyState, ErrorAlert, KeyValue, Loading, Mono, PageHeader, StatusBadge } from '@/components/common'
import { CreateProjectDialog, CreateTaskDialog, RegisterArtifactDialog } from '@/components/forms'
import { TaskTable } from '@/pages/Tasks'
import { RunRow } from '@/pages/Dashboard'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api } from '@/lib/api'
import { timeAgo } from '@/lib/format'

export function Projects() {
  const [q, setQ] = useState('')
  const projects = useQuery({ queryKey: ['projects', q], queryFn: () => api.projects({ q, limit: 200 }) })
  const anonymous = useQuery({ queryKey: ['workspaces', 'anonymous'], queryFn: () => api.workspaces({ anonymous: true }) })
  return (
    <div className="space-y-6">
      <PageHeader title="Projects" description="Directories with a PROJECT_ID file." actions={<CreateProjectDialog />} />
      <Input placeholder="Filter projects…" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-sm" />
      {projects.isLoading && <Loading />}
      {projects.error && <ErrorAlert error={projects.error} />}
      {projects.data && projects.data.items.length === 0 && (
        <EmptyState title="No projects yet">
          Run <Mono>ohmypm project init</Mono> in a project directory.
        </EmptyState>
      )}
      {projects.data && projects.data.items.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Description</TableHead>
              <TableHead>Project ID</TableHead>
              <TableHead className="text-right">Updated</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {projects.data.items.map((p) => (
              <TableRow key={p.id}>
                <TableCell>
                  <Link to={`/projects/${p.id}`} className="font-medium hover:underline">
                    {p.name}
                  </Link>
                </TableCell>
                <TableCell className="max-w-md truncate text-muted-foreground">{p.description}</TableCell>
                <TableCell className="font-mono text-xs">{p.id}</TableCell>
                <TableCell className="text-right text-muted-foreground">{timeAgo(p.updated_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Anonymous workspaces</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-sm">
          {anonymous.data?.items.length === 0 && <div className="text-muted-foreground">None.</div>}
          {anonymous.data?.items.map((w) => (
            <Link key={w.id} to={`/tasks?anonymous=1&workspace_id=${w.id}`} className="block rounded px-2 py-1 font-mono text-xs hover:bg-muted">
              {w.host_id}:{w.root_path}
            </Link>
          ))}
          <Link to="/tasks?anonymous=1" className="block px-2 pt-2 text-xs text-muted-foreground hover:underline">
            All tasks without a project →
          </Link>
        </CardContent>
      </Card>
    </div>
  )
}

export function ProjectView() {
  const { id = '' } = useParams()
  const project = useQuery({ queryKey: ['project', id], queryFn: () => api.project(id), refetchInterval: 10_000 })
  const tasks = useQuery({ queryKey: ['tasks', 'project', id], queryFn: () => api.tasks({ project_id: id, limit: 200, sort: '-updated_at' }) })
  const runs = useQuery({ queryKey: ['runs', 'project', id], queryFn: () => api.runs({ project_id: id, limit: 10 }), refetchInterval: 5000 })
  const artifacts = useQuery({ queryKey: ['artifacts', 'project', id], queryFn: () => api.artifacts({ project_id: id, limit: 20 }) })
  if (project.isLoading) return <Loading />
  if (project.error || !project.data) return <ErrorAlert error={project.error} />
  const p = project.data
  return (
    <div className="space-y-6">
      <PageHeader
        title={p.name}
        description={p.description || <span className="italic">No description</span>}
        actions={
          <>
            <RegisterArtifactDialog projectId={p.id} />
            <CreateTaskDialog projectId={p.id} workspaceId={p.workspaces[0]?.id} />
          </>
        }
      />
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Workspaces</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {p.workspaces.length === 0 && <div className="text-sm text-muted-foreground">No workspace registered yet.</div>}
            {p.workspaces.map((w) => (
              <div key={w.id} className="flex items-center justify-between gap-2 text-sm">
                <Mono>
                  {w.host_id}:{w.root_path}
                </Mono>
                <span className="text-xs text-muted-foreground">seen {timeAgo(w.last_seen_at)}</span>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-0">
            <KeyValue
              items={[
                ['Project ID', <Mono key="id">{p.id}</Mono>],
                ['Tasks', p.stats.tasks_total],
                ['Active runs', p.stats.active_runs],
                ['Pending decisions', p.stats.pending_decisions],
                ['Artifacts', p.stats.artifacts],
              ]}
            />
            <div className="mt-3 flex flex-wrap gap-1">
              {Object.entries(p.stats.tasks_by_status).map(([status, count]) => (
                <span key={status} className="text-xs">
                  <StatusBadge status={status} /> {count}
                </span>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Agent runs</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          {runs.data?.items.length === 0 && <div className="text-sm text-muted-foreground">No runs yet.</div>}
          {runs.data?.items.map((r) => <RunRow key={r.id} run={r} />)}
        </CardContent>
      </Card>
      <div>
        <h2 className="mb-2 font-medium">Tasks</h2>
        {tasks.data && <TaskTable tasks={tasks.data.items} />}
      </div>
      {artifacts.data && artifacts.data.items.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Artifacts</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            {artifacts.data.items.map((a) => (
              <Link key={a.id} to={`/artifacts?id=${a.id}`} className="flex gap-3 rounded px-2 py-1 hover:bg-muted">
                <span className="font-medium">{a.name}</span>
                <span className="text-muted-foreground">{a.type}</span>
                <span className="truncate font-mono text-xs text-muted-foreground">{a.storage_uri}</span>
              </Link>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
