import type {
  Asset,
  ContextResult,
  Dashboard,
  Entry,
  EntryRevision,
  EntryStatus,
  Meta,
  Page,
  Project,
  SearchHit,
  Summary,
  SummarySection,
} from "./types";

/** Error returned by the ohmypm API: `{"error": {"code", "message", "details"}}`. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type Query = Record<string, string | number | boolean | string[] | null | undefined>;

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
    else params.append(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

async function request<T>(method: string, path: string, options: { query?: Query; body?: unknown } = {}): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: {} };
  if (options.body instanceof FormData) {
    init.body = options.body;
  } else if (options.body !== undefined) {
    init.body = JSON.stringify(options.body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), init);
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the ohmypm server. Is `ohmypm web` still running?");
  }
  if (!response.ok) {
    let payload: { error?: { code?: string; message?: string; details?: Record<string, unknown> } } = {};
    try {
      payload = await response.json();
    } catch {
      /* not JSON */
    }
    const err = payload.error ?? {};
    throw new ApiError(response.status, err.code ?? "http_error", err.message ?? response.statusText, err.details);
  }
  return (await response.json()) as T;
}

export interface EntryFilters {
  project_id?: string;
  type?: string[];
  status?: string[];
  q?: string;
  since?: string;
  until?: string;
  order?: "asc" | "desc";
  sort?: "sequence" | "created_at" | "updated_at";
  limit?: number;
  offset?: number;
  include_content?: boolean;
}

export interface EntryInput {
  type: string;
  title: string;
  content: string;
  status?: EntryStatus | null;
  author?: string | null;
  metadata?: Record<string, unknown>;
}

export const api = {
  meta: () => request<Meta>("GET", "/api/meta"),
  dashboard: () => request<Dashboard>("GET", "/api/dashboard"),

  projects: (includeArchived = false) =>
    request<Project[]>("GET", "/api/projects", { query: { include_archived: includeArchived } }),
  project: (id: string) => request<Project>("GET", `/api/projects/${id}`),
  updateProject: (id: string, body: { name?: string; description?: string; root_path?: string }) =>
    request<Project>("PATCH", `/api/projects/${id}`, { body }),
  unregisterProject: (id: string) => request<{ project: Project }>("DELETE", `/api/projects/${id}`),

  entries: (filters: EntryFilters) => request<Page<Entry>>("GET", "/api/entries", { query: { ...filters } }),
  entry: (id: string) => request<Entry>("GET", `/api/entries/${id}`),
  createEntry: (projectId: string, input: EntryInput) =>
    request<Entry>("POST", "/api/entries", { body: { project_id: projectId, ...input } }),
  updateEntry: (
    id: string,
    changes: Partial<EntryInput> & { clear_status?: boolean; expected_revision?: number },
  ) => request<{ changed: boolean; entry: Entry }>("PATCH", `/api/entries/${id}`, { body: changes }),
  deleteEntry: (id: string) => request<{ deleted: boolean }>("DELETE", `/api/entries/${id}`),
  revisions: (id: string) => request<EntryRevision[]>("GET", `/api/entries/${id}/revisions`),
  restoreRevision: (id: string, revision: number) =>
    request<Entry>("POST", `/api/entries/${id}/restore`, { body: { revision } }),

  summary: (projectId: string) => request<Summary>("GET", `/api/projects/${projectId}/summary`),
  saveSummary: (
    projectId: string,
    sections: Partial<Record<SummarySection, string>>,
    expectedRevision?: number,
    author?: string | null,
  ) =>
    request<{ changed: boolean; summary: Summary }>("PUT", `/api/projects/${projectId}/summary`, {
      body: { ...sections, expected_revision: expectedRevision, author: author ?? undefined },
    }),
  context: (projectId: string, mode: string) =>
    request<ContextResult>("GET", `/api/projects/${projectId}/context`, { query: { mode } }),

  search: (q: string, options: { project_id?: string; kind?: string[]; type?: string[]; limit?: number } = {}) =>
    request<Page<SearchHit>>("GET", "/api/search", { query: { q, ...options } }),

  assets: (projectId: string) => request<Asset[]>("GET", "/api/assets", { query: { project_id: projectId } }),
  uploadAsset: (projectId: string, file: File, entryId?: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("project_id", projectId);
    if (entryId) form.append("entry_id", entryId);
    return request<Asset>("POST", "/api/assets", { body: form });
  },
};
