// Mirrors the Pydantic models in src/ohmypm/core/schemas.py.

export type EntryStatus = "open" | "resolved" | "obsolete";

export interface Project {
  id: string;
  name: string;
  root_path: string;
  description: string | null;
  archived: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  last_activity_at: string | null;
  metadata: Record<string, unknown>;
  root_exists: boolean;
  entry_count: number | null;
}

export interface Entry {
  id: string;
  project_id: string;
  sequence: number;
  type: string;
  title: string;
  content: string | null;
  excerpt: string;
  status: EntryStatus | null;
  author: string | null;
  source: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
  asset_ids: string[];
}

export interface EntryRevision {
  id: string;
  entry_id: string;
  sequence: number;
  revision: number;
  type: string;
  title: string;
  content: string;
  status: string | null;
  reason: string;
  changed_by: string | null;
  created_at: string;
}

export const SUMMARY_SECTIONS = [
  "overview",
  "architecture",
  "current_state",
  "important_decisions",
  "known_issues",
  "next_steps",
] as const;
export type SummarySection = (typeof SUMMARY_SECTIONS)[number];

export type Summary = Record<SummarySection, string> & {
  project_id: string;
  revision: number;
  updated_by: string | null;
  updated_at: string | null;
  is_empty: boolean;
};

export interface Asset {
  id: string;
  project_id: string;
  entry_id: string | null;
  filename: string;
  mime_type: string;
  size: number;
  sha256: string;
  created_at: string;
  uri: string;
  markdown: string;
  url: string;
}

export interface SearchHit {
  kind: "entry" | "summary" | "project";
  project_id: string;
  project_name: string;
  ref_id: string;
  title: string;
  snippet: string;
  entry_type: string | null;
  sequence: number | null;
  created_at: string | null;
  score: number | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Meta {
  version: string;
  entry_types: Record<string, string>;
  statuses: EntryStatus[];
  max_upload_bytes: number;
  default_author: string | null;
}

export interface Dashboard {
  projects: Project[];
  recent_entries: (Entry & { project_name: string | null })[];
  recent_summaries: {
    project_id: string;
    project_name: string;
    updated_at: string;
    updated_by: string | null;
    excerpt: string;
  }[];
  type_counts: Record<string, number>;
  total_entries: number;
}

export interface ContextResult {
  mode: string;
  markdown: string;
  budget: { max_tokens: number; used_tokens: number; truncated: boolean };
  stats: { entry_count: number; by_type: Record<string, number>; open_issues: number };
}
