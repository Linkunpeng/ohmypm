import { useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Play, Plus } from 'lucide-react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { api, errorMessage } from '@/lib/api'
import { shortId } from '@/lib/format'
import { ARTIFACT_TYPES, type ContextMode, type Decision, type Task, type TaskPriority } from '@/lib/types'

function Field({ label, htmlFor, hint, children }: { label: string; htmlFor?: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

const lines = (text: string) =>
  text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)

// ---------------------------------------------------------------- projects

export function CreateProjectDialog() {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const qc = useQueryClient()
  const navigate = useNavigate()
  const mutation = useMutation({
    mutationFn: () => api.createProject({ name, description }),
    onSuccess: (project) => {
      void qc.invalidateQueries({ queryKey: ['projects'] })
      setOpen(false)
      toast.success(`Project ${project.name} created`, {
        description: 'Write its id into a PROJECT_ID file, or run `ohmypm project init` in the directory.',
      })
      void navigate(`/projects/${project.id}`)
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus /> New project
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            mutation.mutate()
          }}
        >
          <DialogHeader>
            <DialogTitle>New project</DialogTitle>
            <DialogDescription>
              Usually created from a directory with <code>ohmypm project init</code>, which writes PROJECT_ID.
            </DialogDescription>
          </DialogHeader>
          <Field label="Name" htmlFor="project-name">
            <Input id="project-name" required value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Description" htmlFor="project-description">
            <Textarea id="project-description" value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <DialogFooter>
            <Button type="submit" disabled={mutation.isPending || !name.trim()}>
              Create
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------- tasks

export function CreateTaskDialog({ projectId, workspaceId, trigger }: { projectId?: string; workspaceId?: string; trigger?: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [raw, setRaw] = useState('')
  const [title, setTitle] = useState('')
  const [criteria, setCriteria] = useState('')
  const [priority, setPriority] = useState<TaskPriority>('normal')
  const [workspace, setWorkspace] = useState(workspaceId ?? '')
  const qc = useQueryClient()
  const navigate = useNavigate()
  const workspaces = useQuery({
    queryKey: ['workspaces', projectId ?? 'all'],
    queryFn: () => api.workspaces(projectId ? { project_id: projectId } : { limit: 200 }),
    enabled: open,
  })
  const mutation = useMutation({
    mutationFn: () =>
      api.createTask({
        raw_request: raw,
        title: title.trim() || undefined,
        acceptance_criteria: lines(criteria),
        priority,
        project_id: projectId ?? null,
        workspace_id: workspace || null,
      }),
    onSuccess: (task) => {
      void qc.invalidateQueries({ queryKey: ['tasks'] })
      void qc.invalidateQueries({ queryKey: ['project'] })
      setOpen(false)
      setRaw('')
      setTitle('')
      setCriteria('')
      toast.success(`${task.key} created`)
      void navigate(`/tasks/${task.id}`)
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button size="sm">
            <Plus /> New task
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <form
          className="grid gap-4"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            mutation.mutate()
          }}
        >
          <DialogHeader>
            <DialogTitle>New task</DialogTitle>
            <DialogDescription>The request is stored verbatim; agents add a structured description later.</DialogDescription>
          </DialogHeader>
          <Field label="Request" htmlFor="task-raw">
            <Textarea id="task-raw" required rows={6} value={raw} onChange={(e) => setRaw(e.target.value)} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Title (optional)" htmlFor="task-title" hint="Defaults to the first line of the request">
              <Input id="task-title" value={title} onChange={(e) => setTitle(e.target.value)} />
            </Field>
            <Field label="Priority">
              <Select value={priority} onValueChange={(v) => setPriority(v as TaskPriority)}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(['low', 'normal', 'high', 'urgent'] as const).map((p) => (
                    <SelectItem key={p} value={p}>
                      {p}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </div>
          <Field label="Workspace" hint="Where agents will run. Optional for planning-only tasks.">
            <Select value={workspace || 'none'} onValueChange={(v) => setWorkspace(v === 'none' ? '' : v)}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">No workspace</SelectItem>
                {workspaces.data?.items.map((w) => (
                  <SelectItem key={w.id} value={w.id}>
                    {w.host_id}:{w.root_path}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Acceptance criteria" htmlFor="task-criteria" hint="One per line. Completion requires evidence for each.">
            <Textarea id="task-criteria" rows={3} value={criteria} onChange={(e) => setCriteria(e.target.value)} />
          </Field>
          <DialogFooter>
            <Button type="submit" disabled={mutation.isPending || !raw.trim()}>
              Create task
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function CompleteTaskDialog({ task }: { task: Task }) {
  const [open, setOpen] = useState(false)
  const [summary, setSummary] = useState('')
  const [evidence, setEvidence] = useState<Record<string, string>>({})
  const [force, setForce] = useState(false)
  const qc = useQueryClient()
  const mutation = useMutation({
    mutationFn: () =>
      api.completeTask(task.id, {
        summary,
        force,
        results: task.acceptance_criteria.map((c) => ({
          criterion: c,
          passed: Boolean(evidence[c]?.trim()),
          evidence: evidence[c] ?? '',
        })),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['task', task.id] })
      void qc.invalidateQueries({ queryKey: ['tasks'] })
      setOpen(false)
      toast.success(`${task.key} completed`)
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          Complete…
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Complete {task.key}</DialogTitle>
          <DialogDescription>A task is complete only with acceptance evidence, not because a run exited 0.</DialogDescription>
        </DialogHeader>
        <Field label="Summary" htmlFor="complete-summary">
          <Textarea id="complete-summary" value={summary} onChange={(e) => setSummary(e.target.value)} />
        </Field>
        {task.acceptance_criteria.map((c) => (
          <Field key={c} label={c}>
            <Input
              placeholder="Evidence (command output, link, …)"
              value={evidence[c] ?? ''}
              onChange={(e) => setEvidence((prev) => ({ ...prev, [c]: e.target.value }))}
            />
          </Field>
        ))}
        <div className="flex items-center gap-2">
          <Checkbox id="force" checked={force} onCheckedChange={(v) => setForce(v === true)} />
          <Label htmlFor="force" className="text-sm text-muted-foreground">
            Force (admin override: complete despite missing evidence)
          </Label>
        </div>
        <DialogFooter>
          <Button disabled={!summary.trim() || mutation.isPending} onClick={() => mutation.mutate()}>
            Complete task
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------- dispatch

export function DispatchDialog({
  task,
  defaultAgent,
  fromCheckpointId,
  trigger,
}: {
  task: Task
  defaultAgent?: string
  fromCheckpointId?: string
  trigger?: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const [agent, setAgent] = useState(defaultAgent ?? '')
  const [profile, setProfile] = useState('')
  const [workspace, setWorkspace] = useState(task.workspace_id ?? '')
  const [instructions, setInstructions] = useState('')
  const [mode, setMode] = useState<ContextMode>('standard')
  const [timeout, setTimeoutSeconds] = useState('')
  const [writeMode, setWriteMode] = useState(true)
  const [resumeNative, setResumeNative] = useState(false)
  const [checkpoint, setCheckpoint] = useState(fromCheckpointId ?? '')
  const [force, setForce] = useState(false)
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID())
  const qc = useQueryClient()
  const navigate = useNavigate()

  const agents = useQuery({ queryKey: ['agents'], queryFn: api.agents, enabled: open })
  const profiles = useQuery({ queryKey: ['profiles'], queryFn: api.profiles, enabled: open })
  const workspaces = useQuery({
    queryKey: ['workspaces', task.project_id ?? 'all'],
    queryFn: () => api.workspaces(task.project_id ? { project_id: task.project_id } : { limit: 200 }),
    enabled: open,
  })
  const checkpoints = useQuery({ queryKey: ['checkpoints', task.id], queryFn: () => api.checkpoints(task.id), enabled: open })

  const agentProfiles = useMemo(
    () => (profiles.data ?? []).filter((p) => !agent || p.agent_type === agent),
    [profiles.data, agent],
  )
  const selectedAgent = agents.data?.find((a) => a.agent_type === agent)
  const availableSomewhere = selectedAgent?.available_on.some((r) => r.available && r.online)

  const mutation = useMutation({
    mutationFn: () =>
      api.dispatchRun(
        {
          task_id: task.id,
          agent_type: agent || undefined,
          profile_id: profile || undefined,
          workspace_id: workspace || undefined,
          instructions,
          context_mode: mode,
          timeout_seconds: timeout ? Number(timeout) : undefined,
          write_mode: writeMode,
          resume_native: resumeNative,
          from_checkpoint_id: checkpoint || undefined,
          force,
        },
        idempotencyKey,
      ),
    onSuccess: (run) => {
      void qc.invalidateQueries({ queryKey: ['runs'] })
      void qc.invalidateQueries({ queryKey: ['task', task.id] })
      setOpen(false)
      setIdempotencyKey(crypto.randomUUID())
      toast.success(`Run queued for ${run.agent_type}`)
      void navigate(`/runs/${run.id}`)
    },
    onError: (err) => toast.error(errorMessage(err)),
  })

  const onOpenChange = (next: boolean) => {
    // Defaults may arrive after the first render (e.g. the last run's agent).
    if (next && !agent && defaultAgent) setAgent(defaultAgent)
    if (next && !workspace && task.workspace_id) setWorkspace(task.workspace_id)
    setOpen(next)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button size="sm">
            <Play /> Run agent
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            Assign an agent to {task.key}
          </DialogTitle>
          <DialogDescription>
            The agent starts with the task's recorded context (latest checkpoint, decisions, knowledge) in its workspace.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Agent CLI"
            hint={
              agent && !availableSomewhere ? (
                <span className="text-amber-600">No online runner reports this agent as available; the run will wait.</span>
              ) : undefined
            }
          >
            <Select
              value={agent}
              onValueChange={(v) => {
                setAgent(v)
                setProfile('')
              }}
            >
              <SelectTrigger className="w-full" aria-label="Agent CLI">
                <SelectValue placeholder="Choose an agent" />
              </SelectTrigger>
              <SelectContent>
                {agents.data?.map((a) => {
                  const ok = a.available_on.some((r) => r.available && r.online)
                  return (
                    <SelectItem key={a.agent_type} value={a.agent_type}>
                      {a.display_name ?? a.agent_type} {ok ? '' : '(unavailable)'}
                    </SelectItem>
                  )
                })}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Profile">
            <Select value={profile || 'default'} onValueChange={(v) => setProfile(v === 'default' ? '' : v)}>
              <SelectTrigger className="w-full" aria-label="Profile">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="default">Default for agent</SelectItem>
                {agentProfiles.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name} ({p.agent_type})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Workspace">
            <Select value={workspace} onValueChange={setWorkspace}>
              <SelectTrigger className="w-full" aria-label="Workspace">
                <SelectValue placeholder="Choose a workspace" />
              </SelectTrigger>
              <SelectContent>
                {workspaces.data?.items.map((w) => (
                  <SelectItem key={w.id} value={w.id}>
                    {w.host_id}:{w.root_path}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Context">
            <Select value={mode} onValueChange={(v) => setMode(v as ContextMode)}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="brief">brief</SelectItem>
                <SelectItem value="standard">standard</SelectItem>
                <SelectItem value="full">full</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label="Start from checkpoint">
            <Select value={checkpoint || 'latest'} onValueChange={(v) => setCheckpoint(v === 'latest' ? '' : v)}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="latest">Latest</SelectItem>
                {checkpoints.data?.items.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {new Date(c.created_at).toLocaleString()} — {c.summary.slice(0, 50)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Timeout (seconds)" htmlFor="dispatch-timeout">
            <Input
              id="dispatch-timeout"
              type="number"
              min={1}
              placeholder="profile / server default"
              value={timeout}
              onChange={(e) => setTimeoutSeconds(e.target.value)}
            />
          </Field>
        </div>
        <Field label="Instructions for this run" htmlFor="dispatch-instructions">
          <Textarea
            id="dispatch-instructions"
            rows={4}
            placeholder="Optional. Defaults to continuing toward the acceptance criteria."
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
          />
        </Field>
        <div className="flex flex-wrap gap-5 text-sm">
          <label className="flex items-center gap-2">
            <Switch checked={writeMode} onCheckedChange={setWriteMode} /> Writes to workspace
          </label>
          <label className="flex items-center gap-2">
            <Switch checked={resumeNative} onCheckedChange={setResumeNative} /> Resume native CLI session
          </label>
          <label className="flex items-center gap-2">
            <Checkbox checked={force} onCheckedChange={(v) => setForce(v === true)} /> Ignore unmet dependencies
          </label>
        </div>
        <DialogFooter>
          <Button disabled={!agent || !workspace || mutation.isPending} onClick={() => mutation.mutate()}>
            <Play /> Dispatch
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------- decisions

export function DecisionResolver({ decision }: { decision: Decision }) {
  const [selected, setSelected] = useState<string | null>(null)
  const [response, setResponse] = useState('')
  const [resume, setResume] = useState(false)
  const qc = useQueryClient()
  const mutation = useMutation({
    mutationFn: () => api.resolveDecision(decision.id, { selected_option: selected, response, resume }),
    onSuccess: (res) => {
      void qc.invalidateQueries()
      toast.success('Decision recorded', {
        description: res.resumed_run ? `Run ${shortId(res.resumed_run.id)} queued` : undefined,
      })
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
  const cancel = useMutation({
    mutationFn: () => api.cancelDecision(decision.id, response),
    onSuccess: () => void qc.invalidateQueries(),
    onError: (err) => toast.error(errorMessage(err)),
  })
  if (decision.status !== 'pending') {
    return (
      <div className="text-sm">
        <span className="text-muted-foreground">Answer: </span>
        {decision.selected_option && <strong>{decision.selected_option}</strong>}
        {decision.response && <span> — {decision.response}</span>}
      </div>
    )
  }
  return (
    <div className="grid gap-3">
      {decision.options.length > 0 && (
        <div className="grid gap-2">
          {decision.options.map((o) => (
            <button
              key={o.key}
              type="button"
              onClick={() => setSelected(o.key)}
              className={`rounded-md border p-2 text-left text-sm transition hover:bg-muted ${
                selected === o.key ? 'border-primary ring-2 ring-primary/30' : ''
              }`}
            >
              <div className="font-medium">
                {o.label}
                {decision.recommendation === o.key && (
                  <span className="ml-2 text-xs font-normal text-emerald-600">recommended</span>
                )}
              </div>
              {o.description && <div className="text-xs text-muted-foreground">{o.description}</div>}
            </button>
          ))}
        </div>
      )}
      <Textarea placeholder="Response / extra guidance (optional)" value={response} onChange={(e) => setResponse(e.target.value)} />
      <div className="flex flex-wrap items-center gap-3">
        <Button
          size="sm"
          disabled={mutation.isPending || (decision.options.length > 0 && !selected && !response.trim())}
          onClick={() => mutation.mutate()}
        >
          Submit decision
        </Button>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={resume} onCheckedChange={(v) => setResume(v === true)} /> resume the task's last agent
        </label>
        <Button size="sm" variant="ghost" className="ml-auto" onClick={() => cancel.mutate()}>
          Dismiss
        </Button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- artifacts / knowledge / profiles

export function RegisterArtifactDialog({ taskId, projectId }: { taskId?: string; projectId?: string }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ name: '', type: 'other', uri: '', description: '', usage: '', build: '', version: '' })
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }))
  const qc = useQueryClient()
  const mutation = useMutation({
    mutationFn: () =>
      api.createArtifact({
        name: form.name,
        type: form.type,
        storage_uri: form.uri,
        description: form.description,
        usage: { command: form.usage },
        build: { command: form.build },
        version_label: form.version || null,
        task_id: taskId ?? null,
        project_id: projectId ?? null,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['artifacts'] })
      setOpen(false)
      toast.success('Artifact registered')
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <Plus /> Register artifact
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Register artifact</DialogTitle>
          <DialogDescription>Reference mode: ohmypm records where it lives and how to build/use it.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name">
            <Input value={form.name} onChange={set('name')} />
          </Field>
          <Field label="Type">
            <Select value={form.type} onValueChange={(v) => setForm((f) => ({ ...f, type: v }))}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ARTIFACT_TYPES.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        </div>
        <Field label="Location (path or URI)">
          <Input value={form.uri} onChange={set('uri')} />
        </Field>
        <Field label="Description">
          <Textarea value={form.description} onChange={set('description')} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Usage command">
            <Input value={form.usage} onChange={set('usage')} />
          </Field>
          <Field label="Build command">
            <Input value={form.build} onChange={set('build')} />
          </Field>
          <Field label="Version">
            <Input value={form.version} onChange={set('version')} />
          </Field>
        </div>
        <DialogFooter>
          <Button disabled={!form.name || !form.uri || mutation.isPending} onClick={() => mutation.mutate()}>
            Register
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function KnowledgeDialog({ projectId }: { projectId?: string }) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [category, setCategory] = useState('other')
  const [verified, setVerified] = useState(false)
  const qc = useQueryClient()
  const mutation = useMutation({
    mutationFn: () => api.createKnowledge({ title, content, category, verified, project_id: projectId ?? null }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['knowledge'] })
      setOpen(false)
      setTitle('')
      setContent('')
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus /> Add knowledge
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Add project knowledge</DialogTitle>
          <DialogDescription>Long-lived facts agents should know: architecture, environment, constraints, lessons.</DialogDescription>
        </DialogHeader>
        <Field label="Title">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Category">
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {['architecture', 'environment', 'constraint', 'algorithm', 'experience', 'known_issue', 'other'].map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Content">
          <Textarea rows={6} value={content} onChange={(e) => setContent(e.target.value)} />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={verified} onCheckedChange={(v) => setVerified(v === true)} /> Verified
        </label>
        <DialogFooter>
          <Button disabled={!title || !content || mutation.isPending} onClick={() => mutation.mutate()}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function ProfileDialog() {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [agentType, setAgentType] = useState('claude')
  const [options, setOptions] = useState('{\n  \n}')
  const [isDefault, setIsDefault] = useState(false)
  const [writeMode, setWriteMode] = useState(true)
  const qc = useQueryClient()
  const mutation = useMutation({
    mutationFn: () =>
      api.createProfile({
        name,
        agent_type: agentType,
        options: JSON.parse(options) as Record<string, unknown>,
        is_default: isDefault,
        write_mode: writeMode,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['profiles'] })
      setOpen(false)
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <Plus /> New profile
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Agent profile</DialogTitle>
          <DialogDescription>
            Options are validated against each agent's whitelist (e.g. claude: model, permission_mode, allowed_tools;
            codex: model, sandbox). Elevated modes also need <code>allow_dangerous</code> on the runner.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Agent">
            <Input value={agentType} onChange={(e) => setAgentType(e.target.value)} />
          </Field>
        </div>
        <Field label="Options (JSON)">
          <Textarea className="font-mono text-xs" rows={6} value={options} onChange={(e) => setOptions(e.target.value)} />
        </Field>
        <div className="flex gap-5 text-sm">
          <label className="flex items-center gap-2">
            <Switch checked={isDefault} onCheckedChange={setIsDefault} /> Default for agent
          </label>
          <label className="flex items-center gap-2">
            <Switch checked={writeMode} onCheckedChange={setWriteMode} /> Writes to workspace
          </label>
        </div>
        <DialogFooter>
          <Button disabled={!name || mutation.isPending} onClick={() => mutation.mutate()}>
            Save profile
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
