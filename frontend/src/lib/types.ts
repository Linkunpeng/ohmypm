// Mirrors backend/ohmypm/schemas.py (only the fields the UI uses).

export type TaskStatus = 'todo' | 'in_progress' | 'blocked' | 'awaiting_user' | 'completed' | 'cancelled'
export type TaskPriority = 'low' | 'normal' | 'high' | 'urgent'
export type RunStatus =
  | 'queued'
  | 'starting'
  | 'running'
  | 'waiting_approval'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'interrupted'
  | 'lost'
export type DecisionStatus = 'pending' | 'resolved' | 'cancelled'
export type ContextMode = 'brief' | 'standard' | 'full'

export const TASK_STATUSES: TaskStatus[] = ['todo', 'in_progress', 'blocked', 'awaiting_user', 'completed', 'cancelled']
export const ACTIVE_RUN_STATUSES: RunStatus[] = ['queued', 'starting', 'running', 'waiting_approval']
export const ARTIFACT_TYPES = [
  'executable',
  'script',
  'library',
  'document',
  'model',
  'dataset',
  'resource',
  'container',
  'report',
  'other',
] as const
export type ArtifactType = (typeof ARTIFACT_TYPES)[number]

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export type Json = Record<string, unknown>

export interface Workspace {
  id: string
  project_id: string | null
  host_id: string
  root_path: string
  display_name: string
  created_at: string
  last_seen_at: string
  metadata: Json
}

export interface Project {
  id: string
  name: string
  description: string
  archived: boolean
  created_at: string
  updated_at: string
  created_by: string | null
  metadata: Json
  version: number
}

export interface ProjectDetail extends Project {
  stats: {
    tasks_total: number
    tasks_by_status: Record<string, number>
    active_runs: number
    artifacts: number
    pending_decisions: number
  }
  workspaces: Workspace[]
}

export interface Task {
  id: string
  number: number
  key: string
  project_id: string | null
  workspace_id: string | null
  parent_task_id: string | null
  title: string
  raw_request: string
  description: string
  status: TaskStatus
  priority: TaskPriority
  acceptance_criteria: string[]
  acceptance_result: Json | null
  completed_items: string[]
  remaining_items: string[]
  next_action: string
  blockers: string[]
  tags: string[]
  created_at: string
  updated_at: string
  completed_at: string | null
  created_by: string | null
  metadata: Json
  version: number
}

export interface TaskDetail extends Task {
  depends_on: string[]
  unmet_dependencies: string[]
  dependents: string[]
}

export interface TaskEvent {
  id: number
  task_id: string
  event_type: string
  actor: string | null
  payload: Json
  created_at: string
}

export interface Checkpoint {
  id: string
  task_id: string
  session_id: string | null
  run_id: string | null
  summary: string
  completed: string[]
  remaining: string[]
  current_issue: { description?: string; error?: string; root_cause?: string } | null
  attempts: { action: string; result: string; conclusion?: string }[]
  findings: { statement: string; kind: 'verified' | 'inferred' | 'hypothesis'; evidence?: string }[]
  relevant_files: string[]
  next_steps: string[]
  verification: { command: string; result: string; passed?: boolean | null }[]
  auto_generated: boolean
  created_at: string
  created_by: string | null
}

export interface DecisionOption {
  key: string
  label: string
  description?: string
}

export interface Decision {
  id: string
  task_id: string | null
  project_id: string | null
  question: string
  context: string
  options: DecisionOption[]
  recommendation: string | null
  reasoning: string | null
  status: DecisionStatus
  blocking: boolean
  selected_option: string | null
  response: string | null
  created_at: string
  resolved_at: string | null
  created_by: string | null
  resolved_by: string | null
  version: number
}

export interface Knowledge {
  id: string
  project_id: string | null
  title: string
  category: string
  content: string
  source_task_id: string | null
  verified: boolean
  superseded_by: string | null
  tags: string[]
  created_at: string
  updated_at: string
  created_by: string | null
  version: number
}

export interface Artifact {
  id: string
  task_id: string | null
  project_id: string | null
  name: string
  type: ArtifactType
  storage_mode: string
  storage_uri: string
  sha256: string | null
  size_bytes: number | null
  version_label: string | null
  description: string
  usage: { prerequisites?: string[]; command?: string; expected_result?: string; manual?: string }
  build: { command?: string; source_path?: string; notes?: string }
  environment: Json
  deployment: Json
  verification: { status?: string; checked_at?: string | null; command?: string; result?: string }
  tags: string[]
  created_at: string
  updated_at: string
  created_by: string | null
  version: number
}

export interface ArtifactVersion {
  id: string
  version_label: string | null
  storage_uri: string
  sha256: string | null
  notes: string
  created_at: string
  created_by: string | null
}

export interface ArtifactDetail extends Artifact {
  versions: ArtifactVersion[]
}

export interface Run {
  id: string
  task_id: string
  session_id: string | null
  runner_id: string | null
  workspace_id: string
  agent_type: string
  agent_profile_id: string | null
  profile_snapshot: { name?: string; options?: Json }
  status: RunStatus
  write_mode: boolean
  instructions: string
  context_mode: string
  from_checkpoint_id: string | null
  timeout_seconds: number
  pid: number | null
  exit_code: number | null
  error: string | null
  error_code: string | null
  result_summary: string | null
  usage: Json
  native_session_id: string | null
  command: string[]
  created_at: string
  claimed_at: string | null
  started_at: string | null
  finished_at: string | null
  cancel_requested_at: string | null
  created_by: string | null
}

export interface RunEvent {
  id: number
  run_id: string
  seq: number
  event_type: string
  timestamp: string
  payload: Json
}

export interface Session {
  id: string
  task_id: string
  agent_type: string
  model: string | null
  status: string
  native_session_id: string | null
  created_at: string
}

export interface AgentProfile {
  id: string
  name: string
  agent_type: string
  description: string
  options: Json
  write_mode: boolean
  timeout_seconds: number | null
  is_default: boolean
  version: number
}

export interface AgentAvailability {
  agent_type: string
  display_name: string | null
  available_on: {
    runner_id: string
    runner: string
    host_id: string
    online: boolean
    available: boolean
    version: string | null
    detail: string | null
  }[]
}

export interface Runner {
  id: string
  name: string
  host_id: string
  version: string
  max_parallel: number
  allowed_roots: string[]
  agents: { agent_type: string; available: boolean; version?: string | null; detail?: string | null }[]
  last_heartbeat_at: string
  online: boolean
  active_runs: number
}

export interface ContextOut {
  task_id: string
  mode: ContextMode
  max_tokens: number
  estimated_tokens: number
  truncated: boolean
  sections: string[]
  markdown: string
}

export interface SearchHit {
  kind: string
  id: string
  title: string
  snippet: string
  score: number
  project_id: string | null
  task_id: string | null
  status: string | null
}

export interface Dashboard {
  projects_total: number
  tasks_by_status: Record<string, number>
  tasks_in_progress: Task[]
  tasks_awaiting_user: Task[]
  pending_decisions: Decision[]
  active_runs: Run[]
  recent_runs: Run[]
  recent_artifacts: Artifact[]
  runners_online: number
}
