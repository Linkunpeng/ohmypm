import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import { TypeTag } from "@/components/Badges";
import { Empty, ErrorNotice, Loading, PageHeader } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useDocumentTitle, useProjects } from "@/lib/hooks";
import type { SearchHit } from "@/lib/types";

/** Highlight every query term inside a snippet (case-insensitive, literal match). */
export function highlight(text: string, terms: string[]): ReactNode[] {
  const cleaned = terms.map((t) => t.replace(/^"|"$/g, "")).filter(Boolean);
  if (!cleaned.length) return [text];
  const pattern = new RegExp(`(${cleaned.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text.split(pattern).map((part, i) =>
    i % 2 === 1 ? (
      <mark key={i} className="rounded-sm bg-primary/15 px-0.5 text-foreground">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

function hitLink(hit: SearchHit): string {
  if (hit.kind === "entry") return `/projects/${hit.project_id}/entries/${hit.ref_id}`;
  if (hit.kind === "summary") return `/projects/${hit.project_id}/summary`;
  return `/projects/${hit.project_id}`;
}

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const project = params.get("project") ?? "";
  const kind = params.get("kind") ?? "";
  const [draft, setDraft] = useState(q);
  const { data: projects } = useProjects();
  useDocumentTitle(q ? `Search: ${q}` : "Search");
  useEffect(() => setDraft(q), [q]);

  const results = useQuery({
    queryKey: ["search", q, project, kind],
    queryFn: () => api.search(q, { project_id: project || undefined, kind: kind ? [kind] : undefined, limit: 50 }),
    enabled: q.trim().length > 0,
  });
  const terms = q.match(/"[^"]+"|\S+/g) ?? [];

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  };

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Search">Titles, record text, summaries and project names. Chinese and other scripts work too.</PageHeader>
      <form
        role="search"
        className="mb-6 space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          set("q", draft.trim());
        }}
      >
        <div className="flex gap-2">
          <label htmlFor="search-q" className="sr-only">
            Search terms
          </label>
          <Input
            id="search-q"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder='Words or "an exact phrase"'
            className="h-10 text-base"
            autoFocus
          />
          <Button type="submit" className="h-10">
            <Search /> Search
          </Button>
        </div>
        <div className="flex flex-wrap gap-3 text-sm">
          <label className="flex items-center gap-2">
            <span className="text-muted-foreground">In</span>
            <select
              value={project}
              onChange={(e) => set("project", e.target.value)}
              className="h-8 rounded-md border border-input bg-card px-2"
            >
              <option value="">All projects</option>
              {projects?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2">
            <span className="text-muted-foreground">Find</span>
            <select value={kind} onChange={(e) => set("kind", e.target.value)} className="h-8 rounded-md border border-input bg-card px-2">
              <option value="">Everything</option>
              <option value="entry">Records</option>
              <option value="summary">Summaries</option>
              <option value="project">Projects</option>
            </select>
          </label>
        </div>
      </form>

      {!q ? (
        <Empty title="Type something to search">Tip: put several words to narrow the results; all of them must match.</Empty>
      ) : results.isLoading ? (
        <Loading label="Searching" />
      ) : results.error ? (
        <ErrorNotice error={results.error} what="search results" />
      ) : results.data && results.data.items.length === 0 ? (
        <Empty title={`Nothing matches “${q}”`}>Try fewer or shorter words, or search all projects.</Empty>
      ) : (
        <>
          <p className="mb-3 text-sm text-muted-foreground">
            {results.data?.total} {results.data?.total === 1 ? "result" : "results"}
          </p>
          <ol className="divide-y divide-rule border-y border-rule">
            {results.data?.items.map((hit) => (
              <li key={`${hit.kind}-${hit.ref_id}`}>
                <Link to={hitLink(hit)} className="block py-3 hover:bg-accent/50">
                  <span className="flex flex-wrap items-baseline gap-x-3">
                    {hit.kind === "entry" && <span className="tabular text-sm text-muted-foreground">#{hit.sequence}</span>}
                    <span className="font-medium">
                      {hit.kind === "summary" ? `${hit.project_name} summary` : highlight(hit.title, terms)}
                    </span>
                  </span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
                    {hit.kind === "entry" && hit.entry_type ? <TypeTag type={hit.entry_type} /> : <span>{hit.kind === "summary" ? "Summary" : "Project"}</span>}
                    {hit.kind !== "project" && <span>{hit.project_name}</span>}
                    {hit.created_at && <span>{formatDate(hit.created_at)}</span>}
                  </span>
                  {hit.snippet && <span className="mt-1 block font-serif text-[0.95rem] text-foreground/80">{highlight(hit.snippet, terms)}</span>}
                </Link>
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}
