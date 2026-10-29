import { clearToken, getToken } from './auth'
import type {
  AgentAvailability,
  AgentProfile,
  Artifact,
  ArtifactDetail,
  Checkpoint,
  ContextMode,
  ContextOut,
  Dashboard,
  Decision,
  Knowledge,
  Page,
  Project,
  ProjectDetail,
  Run,
  RunEvent,
  Runner,
  SearchHit,
  Session,
  Task,
  TaskDetail,
  TaskEvent,
  Workspace,
} from './types'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

type Query = Record<string, string | number | boolean | string[] | null | undefined>

export function buildQuery(params?: Query): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v))
    else search.append(key, String(value))
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}

let onUnauthorized: () => void = () => undefined
export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn
}

export async function request<T>(method: string, path: string, body?: unknown, headers?: HeadersInit): Promise<T> {
  const token = getToken()
  const res = await fetch(path, {
    method,
    headers: {
      Accept: 'application/json',
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (res.status === 204) return undefined as T
  const text = await res.text()
  const data: unknown = text ? JSON.parse(text) : undefined
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string; details?: unknown } } | undefined)?.error
    if (res.status === 401) {
      clearToken()
      onUnauthorized()
    }
    throw new ApiError(res.status, err?.code ?? 'http_error', err?.message ?? res.statusText, err?.details)
  }
  return data as T
}

const get = <T>(path: string, params?: Query) => request<T>('GET', path + buildQuery(params))
const post = <T>(path: string, body?: unknown, headers?: HeadersInit) => request<T>('POST', path, body ?? {}, headers)
const patch = <T>(path: string, body: unknown) => request<T>('PATCH', path, body)

export const api = {
  health: () => get<{ status: string; version: string; database: string; schema_revision: string | null }>('/api/health'),
  whoami: () => get<{ role: string; name: string }>('/api/whoami'),
  dashboard: () => get<Dashboard>('/api/dashboard'),
  search: (q: string, kind?: string[]) => get<{ query: string; hits: SearchHit[] }>('/api/search', { q, kind }),

  projects: (params?: Query) => get<Page<Project>>('/api/projects', params),
  project: (id: string) => get<ProjectDetail>(`/api/projects/${id}`),
  createProject: (body: { name: string; description?: string }) => post<Project>('/api/projects', body),
  updateProject: (id: string, body: Partial<Project> & { expected_version?: number }) =>
    patch<Project>(`/api/projects/${id}`, body),

  workspaces: (params?: Query) => get<Page<Workspace>>('/api/workspaces', params),

  tasks: (params?: Query) => get<Page<Task>>('/api/tasks', params),
  task: (ref: string) => get<TaskDetail>(`/api/tasks/${ref}`),
  createTask: (body: Partial<Task> & { raw_request: string; depends_on?: string[] }) =>
    post<Task>('/api/tasks', body),
  updateTask: (id: string, body: Record<string, unknown>) => patch<Task>(`/api/tasks/${id}`, body),
  completeTask: (id: string, body: { summary: string; results: { criterion: string; passed: boolean; evidence: string }[]; force?: boolean }) =>
    post<Task>(`/api/tasks/${id}/complete`, body),
  taskEvents: (id: string) => get<TaskEvent[]>(`/api/tasks/${id}/events`, { limit: 1000 }),
  taskContext: (id: string, mode: ContextMode, maxTokens?: number) =>
    get<ContextOut>(`/api/tasks/${id}/context`, { mode, max_tokens: maxTokens }),
  checkpoints: (id: string) => get<Page<Checkpoint>>(`/api/tasks/${id}/checkpoints`, { limit: 100 }),
  sessions: (id: string) => get<Session[]>(`/api/tasks/${id}/sessions`),
  addDependency: (id: string, dependsOn: string) =>
    post<void>(`/api/tasks/${id}/dependencies`, { depends_on_id: dependsOn }),

  decisions: (params?: Query) => get<Page<Decision>>('/api/decisions', params),
  resolveDecision: (id: string, body: { selected_option?: string | null; response?: string; resume?: boolean }) =>
    post<{ decision: Decision; resumed_run: Run | null }>(`/api/decisions/${id}/resolve`, body),
  cancelDecision: (id: string, reason: string) => post<Decision>(`/api/decisions/${id}/cancel`, { reason }),

  knowledge: (params?: Query) => get<Page<Knowledge>>('/api/knowledge', params),
  createKnowledge: (body: Partial<Knowledge> & { title: string; content: string }) =>
    post<Knowledge>('/api/knowledge', body),
  updateKnowledge: (id: string, body: Record<string, unknown>) => patch<Knowledge>(`/api/knowledge/${id}`, body),

  artifacts: (params?: Query) => get<Page<Artifact>>('/api/artifacts', params),
  artifact: (id: string) => get<ArtifactDetail>(`/api/artifacts/${id}`),
  createArtifact: (body: Record<string, unknown>) => post<Artifact>('/api/artifacts', body),
  updateArtifact: (id: string, body: Record<string, unknown>) => patch<Artifact>(`/api/artifacts/${id}`, body),

  runs: (params?: Query) => get<Page<Run>>('/api/runs', params),
  run: (id: string) => get<Run>(`/api/runs/${id}`),
  runEvents: (id: string, afterSeq = 0) => get<RunEvent[]>(`/api/runs/${id}/events`, { after_seq: afterSeq, limit: 2000 }),
  dispatchRun: (body: Record<string, unknown>, idempotencyKey?: string) =>
    post<Run>('/api/runs', body, idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined),
  cancelRun: (id: string, reason = '') => post<Run>(`/api/runs/${id}/cancel`, { reason }),

  runners: () => get<Runner[]>('/api/runners'),
  agents: () => get<AgentAvailability[]>('/api/agents'),
  profiles: () => get<AgentProfile[]>('/api/agent-profiles'),
  createProfile: (body: Record<string, unknown>) => post<AgentProfile>('/api/agent-profiles', body),
  deleteProfile: (id: string) => request<void>('DELETE', `/api/agent-profiles/${id}`),
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return `${err.message} (${err.code})`
  if (err instanceof Error) return err.message
  return String(err)
}
