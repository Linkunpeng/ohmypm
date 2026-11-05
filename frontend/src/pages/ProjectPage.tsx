import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDownUp, Bot, FileText, Pencil, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";

import { Empty, ErrorNotice, Loading, PageHeader } from "@/components/common";
import { MarkdownView } from "@/components/markdown/MarkdownView";
import { Timeline } from "@/components/Timeline";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { TYPE_ORDER, typeStyle } from "@/lib/entryTypes";
import { timeAgo } from "@/lib/format";
import { queryKeys, useAssets, useDocumentTitle, useMeta, useProject } from "@/lib/hooks";
import type { Project } from "@/lib/types";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 40;

function EditProjectDialog({ project, open, onOpenChange }: { project: Project; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const client = useQueryClient();
  const save = useMutation({
    mutationFn: () => api.updateProject(project.id, { name, description }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.project(project.id) });
      void client.invalidateQueries({ queryKey: queryKeys.projects });
      toast.success("Project details saved");
      onOpenChange(false);
    },
    onError: (err) => toast.error(err.message),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Project details</DialogTitle>
        </DialogHeader>
        <form
          id="project-form"
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="project-name">Name</Label>
            <Input id="project-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="project-description">Description</Label>
            <Textarea id="project-description" value={description} onChange={(e) => setDescription(e.target.value)} rows={3} />
          </div>
          <p className="text-xs text-muted-foreground">
            The directory is changed with <code className="font-mono">ohmypm project relink</code>.
          </p>
        </form>
        <DialogFooter>
          <Button type="submit" form="project-form" disabled={save.isPending}>
            Save details
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ProjectPage() {
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const [editing, setEditing] = useState(false);
  const { data: project, error } = useProject(projectId);
  const { data: meta } = useMeta();
  const { data: assetList } = useAssets(projectId);
  const summary = useQuery({ queryKey: queryKeys.summary(projectId), queryFn: () => api.summary(projectId) });
  useDocumentTitle(project?.name);

  const types = params.getAll("type");
  const status = params.get("status") ?? "";
  const q = params.get("q") ?? "";
  const since = params.get("since") ?? "";
  const until = params.get("until") ?? "";
  const order = params.get("order") === "desc" ? "desc" : "asc";
  const [draftQuery, setDraftQuery] = useState(q);

  const update = (mutate: (p: URLSearchParams) => void) => {
    const next = new URLSearchParams(params);
    mutate(next);
    setParams(next, { replace: true });
  };

  const entries = useInfiniteQuery({
    queryKey: [...queryKeys.entries(projectId), { types, status, q, since, until, order }],
    queryFn: ({ pageParam }) =>
      api.entries({
        project_id: projectId,
        type: types,
        status: status ? [status] : undefined,
        q: q || undefined,
        since: since || undefined,
        until: until || undefined,
        order,
        limit: PAGE_SIZE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined),
  });

  const assets = useMemo(() => new Map((assetList ?? []).map((a) => [a.id, a])), [assetList]);
  const items = entries.data?.pages.flatMap((p) => p.items) ?? [];
  const total = entries.data?.pages[0]?.total ?? 0;
  const typeOptions = [...TYPE_ORDER, ...Object.keys(meta?.entry_types ?? {}).filter((t) => !TYPE_ORDER.includes(t))];
  const filtered = types.length > 0 || !!status || !!q || !!since || !!until;

  if (error) return <ErrorNotice error={error} what="this project" />;
  if (!project) return <Loading />;

  const s = summary.data;

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title={project.name}
        actions={
          <>
            <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
              <Pencil /> Details
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link to={`/projects/${project.id}/context`}>
                <Bot /> Agent context
              </Link>
            </Button>
            <Button size="sm" asChild>
              <Link to={`/projects/${project.id}/entries/new`}>
                <Plus /> New record
              </Link>
            </Button>
          </>
        }
      >
        <span className="font-mono text-xs" title="Project directory">
          {project.root_path}
        </span>
        {!project.root_exists && <span className="ml-2 text-destructive">directory not found</span>}
        {project.description && <p className="mt-2 max-w-[70ch] text-[0.95rem] text-foreground/80">{project.description}</p>}
      </PageHeader>
      <EditProjectDialog key={String(editing)} project={project} open={editing} onOpenChange={setEditing} />

      {/* summary strip */}
      <section aria-labelledby="summary-heading" className="mb-10 rounded-md border border-border bg-card p-5">
        <div className="mb-3 flex items-baseline justify-between gap-4">
          <h2 id="summary-heading" className="font-medium">
            Summary
          </h2>
          <Link to={`/projects/${project.id}/summary`} className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
            <FileText className="size-3.5" aria-hidden />
            {s?.is_empty ? "Write the summary" : "Full summary"}
          </Link>
        </div>
        {s?.is_empty ? (
          <p className="text-sm text-muted-foreground">
            No summary yet. It holds the current state, known issues and next steps that agents read first.
          </p>
        ) : s ? (
          <div className="grid gap-6 md:grid-cols-2">
            {(["current_state", "next_steps"] as const).map((key) => (
              <div key={key} className="min-w-0">
                <h3 className="mb-1 text-xs font-medium text-muted-foreground">
                  {key === "current_state" ? "Current state" : "Next steps"}
                </h3>
                {s[key] ? (
                  <MarkdownView markdown={s[key]} className="line-clamp-[8] text-[0.95rem]" />
                ) : (
                  <p className="text-sm text-muted-foreground">Not written yet.</p>
                )}
              </div>
            ))}
          </div>
        ) : null}
        {s?.updated_at && (
          <p className="mt-3 text-xs text-muted-foreground">
            Updated {timeAgo(s.updated_at)}
            {s.updated_by ? ` by ${s.updated_by}` : ""}
          </p>
        )}
      </section>

      {/* filters */}
      <section aria-labelledby="timeline-heading">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <h2 id="timeline-heading" className="font-medium">
            Timeline <span className="font-normal text-muted-foreground">{total} {filtered ? "matching" : ""} records</span>
          </h2>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => update((p) => (order === "asc" ? p.set("order", "desc") : p.delete("order")))}
          >
            <ArrowDownUp /> {order === "asc" ? "Oldest first" : "Newest first"}
          </Button>
        </div>
        <div className="mb-6 space-y-3 border-b border-rule pb-4">
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by type">
            {typeOptions.map((t) => {
              const active = types.includes(t);
              return (
                <button
                  key={t}
                  type="button"
                  aria-pressed={active}
                  onClick={() =>
                    update((p) => {
                      const next = active ? types.filter((x) => x !== t) : [...types, t];
                      p.delete("type");
                      next.forEach((x) => p.append("type", x));
                    })
                  }
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-sm",
                    active ? "border-primary bg-accent text-foreground" : "border-border text-muted-foreground hover:text-foreground",
                  )}
                >
                  <span aria-hidden className="size-2 rounded-[2px]" style={{ background: typeStyle(t).color }} />
                  {typeStyle(t).label}
                </button>
              );
            })}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <form
              className="min-w-48 flex-1"
              onSubmit={(e) => {
                e.preventDefault();
                update((p) => (draftQuery.trim() ? p.set("q", draftQuery.trim()) : p.delete("q")));
              }}
            >
              <Label htmlFor="filter-q" className="mb-1 text-xs text-muted-foreground">
                Contains
              </Label>
              <Input
                id="filter-q"
                value={draftQuery}
                onChange={(e) => setDraftQuery(e.target.value)}
                onBlur={() => update((p) => (draftQuery.trim() ? p.set("q", draftQuery.trim()) : p.delete("q")))}
                placeholder="Words in title or text"
                className="h-8"
              />
            </form>
            <div>
              <Label htmlFor="filter-status" className="mb-1 text-xs text-muted-foreground">
                Status
              </Label>
              <select
                id="filter-status"
                value={status}
                onChange={(e) => update((p) => (e.target.value ? p.set("status", e.target.value) : p.delete("status")))}
                className="h-8 rounded-md border border-input bg-card px-2 text-sm"
              >
                <option value="">Any</option>
                <option value="open">Open</option>
                <option value="resolved">Resolved</option>
                <option value="obsolete">Obsolete</option>
                <option value="none">No status</option>
              </select>
            </div>
            <div>
              <Label htmlFor="filter-since" className="mb-1 text-xs text-muted-foreground">
                From
              </Label>
              <Input
                id="filter-since"
                type="date"
                value={since}
                onChange={(e) => update((p) => (e.target.value ? p.set("since", e.target.value) : p.delete("since")))}
                className="h-8 w-38"
              />
            </div>
            <div>
              <Label htmlFor="filter-until" className="mb-1 text-xs text-muted-foreground">
                To
              </Label>
              <Input
                id="filter-until"
                type="date"
                value={until}
                onChange={(e) => update((p) => (e.target.value ? p.set("until", e.target.value) : p.delete("until")))}
                className="h-8 w-38"
              />
            </div>
            {filtered && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setDraftQuery("");
                  update((p) => ["type", "status", "q", "since", "until"].forEach((k) => p.delete(k)));
                }}
              >
                Clear filters
              </Button>
            )}
          </div>
        </div>

        {entries.error ? (
          <ErrorNotice error={entries.error} what="records" />
        ) : entries.isLoading ? (
          <Loading label="Loading records" />
        ) : items.length === 0 ? (
          filtered ? (
            <Empty title="No records match these filters" />
          ) : (
            <Empty title="No records yet">
              Add the first one with <Link className="text-primary underline" to={`/projects/${project.id}/entries/new`}>New record</Link>{" "}
              or let an agent run <code>ohmypm log add</code>.
            </Empty>
          )
        ) : (
          <>
            <Timeline entries={items} projectId={project.id} assets={assets} />
            {entries.hasNextPage && (
              <div className="mt-6 flex justify-center">
                <Button variant="outline" onClick={() => entries.fetchNextPage()} disabled={entries.isFetchingNextPage}>
                  {entries.isFetchingNextPage ? "Loading…" : `Show more (${total - items.length} left)`}
                </Button>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}
