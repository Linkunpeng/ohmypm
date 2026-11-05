import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useBlocker, useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { ErrorNotice, Loading, PageHeader } from "@/components/common";
import { MarkdownEditor, type EditorMode } from "@/components/editor/MarkdownEditor";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";
import { TYPE_ORDER, typeStyle } from "@/lib/entryTypes";
import { queryKeys, useAuthor, useDocumentTitle, useMeta, useProject } from "@/lib/hooks";
import type { Entry, EntryStatus } from "@/lib/types";

const TEMPLATES: Record<string, string> = {
  milestone: "## What was done\n\n## Key implementation\n\n## Verification\n\n## Next steps\n",
  issue: "## Symptoms\n\n## Relevant files\n\n## Attempts\n\n## Confirmed findings\n\n## Next steps\n",
  decision: "## Context\n\n## Options considered\n\n## Decision and rationale\n",
  artifact: "## Location\n\n## Build\n\n## Usage\n\n## Verification\n",
};

function EntryForm({ projectId, entry }: { projectId: string; entry?: Entry }) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [author] = useAuthor();
  const { data: meta } = useMeta();
  const [title, setTitle] = useState(entry?.title ?? "");
  const [type, setType] = useState(entry?.type ?? "note");
  const [status, setStatus] = useState<EntryStatus | "">(entry?.status ?? "");
  const [content, setContent] = useState(entry?.content ?? "");
  const [mode, setMode] = useState<EditorMode>("rich");
  const [notice, setNotice] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const saved = useRef(false);
  const [original] = useState({ title, type, status, content });

  const dirty =
    title !== original.title || type !== original.type || status !== original.status || content !== original.content;
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && !saved.current && currentLocation.pathname !== nextLocation.pathname);

  useEffect(() => {
    if (blocker.state === "blocked") {
      if (window.confirm("Discard unsaved changes to this record?")) blocker.proceed();
      else blocker.reset();
    }
  }, [blocker]);

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (dirty && !saved.current) e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  const types = [...TYPE_ORDER, ...Object.keys(meta?.entry_types ?? {}).filter((t) => !TYPE_ORDER.includes(t))];

  const save = useMutation({
    mutationFn: async () => {
      if (entry) {
        const changes: Parameters<typeof api.updateEntry>[1] = { expected_revision: entry.revision, author };
        if (title !== entry.title) changes.title = title;
        if (type !== entry.type) changes.type = type;
        if (content !== (entry.content ?? "")) changes.content = content;
        if (status !== (entry.status ?? "")) {
          if (status) changes.status = status;
          else changes.clear_status = true;
        }
        return (await api.updateEntry(entry.id, changes)).entry;
      }
      return api.createEntry(projectId, { type, title, content, status: status || null, author });
    },
    onSuccess: (result) => {
      saved.current = true;
      client.setQueryData(queryKeys.entry(result.id), result);
      void client.invalidateQueries({ queryKey: queryKeys.entries(projectId) });
      void client.invalidateQueries({ queryKey: queryKeys.dashboard });
      void client.invalidateQueries({ queryKey: queryKeys.projects });
      void client.invalidateQueries({ queryKey: queryKeys.assets(projectId) });
      toast.success(entry ? "Record saved" : `Record #${result.sequence} added`);
      navigate(`/projects/${projectId}/entries/${result.id}`);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.code === "conflict") setConflict(true);
      else toast.error(err.message);
    },
  });

  return (
    <form
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (!title.trim()) {
          toast.error("Give the record a title");
          return;
        }
        save.mutate();
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="entry-title">Title</Label>
        <Input
          id="entry-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="What happened, in a few words"
          maxLength={500}
          required
          className="h-10 text-base"
          autoFocus={!entry}
        />
      </div>

      <div className="flex flex-wrap gap-6">
        <fieldset>
          <legend className="mb-1.5 text-sm font-medium">Type</legend>
          <div className="flex flex-wrap gap-1.5">
            {types.map((t) => (
              <label
                key={t}
                className="inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-border px-2.5 py-0.5 text-sm text-muted-foreground has-checked:border-primary has-checked:bg-accent has-checked:text-foreground has-focus-visible:ring-2 has-focus-visible:ring-ring"
              >
                <input
                  type="radio"
                  name="type"
                  value={t}
                  checked={type === t}
                  onChange={() => {
                    setType(t);
                    if (!entry && !content.trim() && TEMPLATES[t]) {
                      setContent(TEMPLATES[t]);
                      setMode("markdown");
                    }
                    if (!entry && t === "issue" && !status) setStatus("open");
                  }}
                  className="sr-only"
                />
                <span aria-hidden className="size-2 rounded-[2px]" style={{ background: typeStyle(t).color }} />
                {typeStyle(t).label}
              </label>
            ))}
          </div>
        </fieldset>
        <div>
          <Label htmlFor="entry-status" className="mb-1.5">
            Status
          </Label>
          <select
            id="entry-status"
            value={status}
            onChange={(e) => setStatus(e.target.value as EntryStatus | "")}
            className="h-8 rounded-md border border-input bg-card px-2 text-sm"
          >
            <option value="">None</option>
            <option value="open">Open</option>
            <option value="resolved">Resolved</option>
            <option value="obsolete">Obsolete</option>
          </select>
        </div>
      </div>

      <div className="space-y-1.5">
        <span className="text-sm font-medium" id="content-label">
          Text
        </span>
        {notice && (
          <p role="status" className="flex items-start gap-2 rounded-md bg-accent px-3 py-2 text-sm">
            <Info className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
            {notice}
          </p>
        )}
        <MarkdownEditor
          value={content}
          onChange={setContent}
          projectId={projectId}
          entryId={entry?.id}
          mode={mode}
          onModeChange={(m) => {
            setMode(m);
            if (m === "markdown") setNotice(null);
          }}
          onLossyRichText={(reason) => {
            setMode("markdown");
            setNotice(reason);
          }}
          placeholder="Markdown: code blocks, tables, images, ```mermaid diagrams and $\\LaTeX$ formulas are supported."
        />
      </div>

      {conflict && (
        <div role="alert" className="rounded-md border border-destructive/40 p-3 text-sm">
          This record was changed elsewhere (for example by an agent) after you opened it. Copy your text, then{" "}
          <button type="button" className="text-primary underline" onClick={() => window.location.reload()}>
            reload the latest version
          </button>
          .
        </div>
      )}

      <div className="flex items-center gap-3 border-t border-rule pt-4">
        <Button type="submit" disabled={save.isPending}>
          {entry ? "Save record" : "Add record"}
        </Button>
        <Button type="button" variant="ghost" asChild>
          <Link to={entry ? `/projects/${projectId}/entries/${entry.id}` : `/projects/${projectId}`}>Cancel</Link>
        </Button>
        <span className="text-xs text-muted-foreground">Recorded as {author}</span>
      </div>
    </form>
  );
}

export function EntryEditPage() {
  const { projectId = "", entryId } = useParams();
  const { data: project } = useProject(projectId);
  const entry = useQuery({
    queryKey: queryKeys.entry(entryId ?? ""),
    queryFn: () => api.entry(entryId!),
    enabled: !!entryId,
  });
  useDocumentTitle(entryId ? "Edit record" : "New record");

  if (entryId && entry.isLoading) return <Loading />;
  if (entryId && (entry.error || !entry.data)) return <ErrorNotice error={entry.error} what="this record" />;

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title={entry.data ? `Edit record ${entry.data.sequence}` : "New record"}>
        {project?.name}
      </PageHeader>
      <EntryForm key={entry.data?.id ?? "new"} projectId={projectId} entry={entry.data} />
    </div>
  );
}
