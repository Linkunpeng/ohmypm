import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { api } from "./api";

export const queryKeys = {
  meta: ["meta"] as const,
  dashboard: ["dashboard"] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["project", id] as const,
  entries: (projectId: string) => ["entries", projectId] as const,
  entry: (id: string) => ["entry", id] as const,
  summary: (projectId: string) => ["summary", projectId] as const,
  assets: (projectId: string) => ["assets", projectId] as const,
};

export function useMeta() {
  return useQuery({ queryKey: queryKeys.meta, queryFn: api.meta, staleTime: Infinity });
}

export function useProjects() {
  return useQuery({ queryKey: queryKeys.projects, queryFn: () => api.projects() });
}

export function useProject(id: string | undefined) {
  return useQuery({ queryKey: queryKeys.project(id ?? ""), queryFn: () => api.project(id!), enabled: !!id });
}

export function useAssets(projectId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.assets(projectId ?? ""),
    queryFn: () => api.assets(projectId!),
    enabled: !!projectId,
  });
}

const AUTHOR_KEY = "ohmypm-author";

/** The name recorded as author for entries created in the browser. */
export function useAuthor(): [string, (name: string) => void] {
  const { data: meta } = useMeta();
  const [stored, setStored] = useState<string | null>(() => {
    try {
      return localStorage.getItem(AUTHOR_KEY);
    } catch {
      return null;
    }
  });
  const set = useCallback((name: string) => {
    setStored(name);
    try {
      localStorage.setItem(AUTHOR_KEY, name);
    } catch {
      /* ignore */
    }
  }, []);
  return [stored ?? meta?.default_author ?? "user", set];
}

export function useDocumentTitle(title: string | undefined) {
  useEffect(() => {
    document.title = title ? `${title} · ohmypm` : "ohmypm";
  }, [title]);
}
