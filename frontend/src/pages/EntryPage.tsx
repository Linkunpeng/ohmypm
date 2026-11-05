import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, History, Paperclip, Pencil, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { StatusTag, TypeTag } from "@/components/Badges";
import { ErrorNotice, Loading } from "@/components/common";
import { MarkdownView } from "@/components/markdown/MarkdownView";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { formatBytes, formatDateTime } from "@/lib/format";
import { queryKeys, useAssets, useAuthor, useDocumentTitle, useProject } from "@/lib/hooks";
import type { Entry } from "@/lib/types";

function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[6rem_minmax(0,1fr)] gap-2 py-1.5 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

function RevisionsDialog({ entry, open, onOpenChange }: { entry: Entry; open: boolean; onOpenChange: (o: boolean) => void }) {
  const client = useQueryClient();
  const [selected, setSelected] = useState<number | null>(null);
  const revisions = useQuery({
    queryKey: ["revisions", entry.id, entry.revision],
    queryFn: () => api.revisions(entry.id),
    enabled: open,
  });
  const restore = useMutation({
    mutationFn: (revision: number) => api.restoreRevision(entry.id, revision),
    onSuccess: (updated) => {
      client.setQueryData(queryKeys.entry(entry.id), updated);
      void client.invalidateQueries({ queryKey: queryKeys.entries(entry.project_id) });
      toast.success(`Restored revision ${selected}`);
      onOpenChange(false);
    },
    onError: (err) => toast.error(err.message),
  });
  const list = [...(revisions.data ?? [])].reverse();
  const shown = list.find((r) => r.revision === selected) ?? list[0];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-hidden sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Earlier versions of #{entry.sequence}</DialogTitle>
        </DialogHeader>
        {revisions.isLoading ? (
          <Loading />
        ) : list.length === 0 ? (
          <p className="text-sm text-muted-foreground">This record has not been edited.</p>
        ) : (
          <div className="grid min-h-0 gap-4 md:grid-cols-[13rem_minmax(0,1fr)]">
            <ul className="space-y-1 overflow-y-auto">
              {list.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(r.revision)}
                    className={`w-full rounded px-2 py-1.5 text-left text-sm hover:bg-accent ${shown?.revision === r.revision ? "bg-accent" : ""}`}
                  >
                    <span className="block font-medium">Revision {r.revision}</span>
                    <span className="block text-xs text-muted-foreground">
                      replaced {formatDateTime(r.created_at)}
                      {r.changed_by ? ` by ${r.changed_by}` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {shown && (
              <div className="min-h-0 space-y-3 overflow-y-auto rounded border border-rule p-4" style={{ maxHeight: "60vh" }}>
                <p className="font-medium">{shown.title}</p>
                <MarkdownView markdown={shown.content} />
              </div>
            )}
          </div>
        )}
        {shown && (
          <div className="flex justify-end">
            <Button onClick={() => restore.mutate(shown.revision)} disabled={restore.isPending}>
              <RotateCcw /> Restore revision {shown.revision}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function EntryPage() {
  const { projectId = "", entryId = "" } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [author] = useAuthor();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [showRevisions, setShowRevisions] = useState(false);
  const { data: project } = useProject(projectId);
  const { data: assets } = useAssets(projectId);
  const { data: entry, error, isLoading } = useQuery({
    queryKey: queryKeys.entry(entryId),
    queryFn: () => api.entry(entryId),
  });
  useDocumentTitle(entry ? `#${entry.sequence} ${entry.title}` : undefined);

  const invalidate = () => {
    void client.invalidateQueries({ queryKey: queryKeys.entries(projectId) });
    void client.invalidateQueries({ queryKey: queryKeys.dashboard });
    void client.invalidateQueries({ queryKey: queryKeys.projects });
  };

  const setStatus = useMutation({
    mutationFn: (status: "resolved" | "open") =>
      api.updateEntry(entryId, { status, expected_revision: entry?.revision, author }),
    onSuccess: ({ entry: updated }) => {
      client.setQueryData(queryKeys.entry(entryId), updated);
      invalidate();
      toast.success(updated.status === "resolved" ? "Marked as resolved" : "Reopened");
    },
    onError: (err) => toast.error(err.message),
  });

  const remove = useMutation({
    mutationFn: () => api.deleteEntry(entryId),
    onSuccess: () => {
      invalidate();
      toast.success("Record deleted. Its last version is kept and can be listed with `ohmypm log deleted`.");
      navigate(`/projects/${projectId}`);
    },
    onError: (err) => toast.error(err.message),
  });

  if (isLoading) return <Loading />;
  if (error || !entry) return <ErrorNotice error={error ?? "not found"} what="this record" />;

  const attachments = (assets ?? []).filter((a) => entry.asset_ids.includes(a.id) || a.entry_id === entry.id);
  const metadata = Object.entries(entry.metadata);

  return (
    <div className="mx-auto max-w-6xl">
      <nav aria-label="Breadcrumb" className="mb-4 text-sm text-muted-foreground">
        <Link to={`/projects/${projectId}`} className="hover:text-foreground hover:underline">
          {project?.name ?? "Project"}
        </Link>
        <span className="mx-1.5">/</span>
        <span>Record {entry.sequence}</span>
      </nav>

      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <article className="min-w-0">
          <header className="mb-6 border-b border-rule pb-5">
            <div className="flex items-start gap-4">
              <span className="pt-1 text-2xl font-medium tabular text-muted-foreground" aria-label="Sequence number">
                {entry.sequence}
              </span>
              <div className="min-w-0 flex-1">
                <h1 className="text-2xl leading-snug font-semibold tracking-tight text-balance">{entry.title}</h1>
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  <TypeTag type={entry.type} className="text-sm" />
                  <StatusTag status={entry.status} />
                </div>
              </div>
            </div>
          </header>
          {entry.content?.trim() ? (
            <MarkdownView markdown={entry.content} className="max-w-[76ch]" />
          ) : (
            <p className="text-muted-foreground">This record has no body text.</p>
          )}
        </article>

        <aside className="space-y-6 lg:sticky lg:top-6 lg:self-start">
          <div className="flex flex-wrap gap-2">
            <Button size="sm" asChild>
              <Link to={`/projects/${projectId}/entries/${entry.id}/edit`}>
                <Pencil /> Edit
              </Link>
            </Button>
            {entry.type === "issue" && entry.status === "open" && (
              <Button size="sm" variant="outline" onClick={() => setStatus.mutate("resolved")} disabled={setStatus.isPending}>
                <CheckCircle2 /> Mark resolved
              </Button>
            )}
            {entry.type === "issue" && entry.status === "resolved" && (
              <Button size="sm" variant="outline" onClick={() => setStatus.mutate("open")} disabled={setStatus.isPending}>
                Reopen
              </Button>
            )}
          </div>

          <dl className="divide-y divide-rule border-y border-rule">
            <MetaRow label="Created">{formatDateTime(entry.created_at)}</MetaRow>
            {entry.updated_at !== entry.created_at && (
              <MetaRow label="Updated">
                {formatDateTime(entry.updated_at)} <span className="text-muted-foreground">(revision {entry.revision})</span>
              </MetaRow>
            )}
            <MetaRow label="Author">{entry.author ?? <span className="text-muted-foreground">unknown</span>}</MetaRow>
            <MetaRow label="Added via">{entry.source ?? "—"}</MetaRow>
            {metadata.map(([k, v]) => (
              <MetaRow key={k} label={k}>
                <span className="font-mono text-xs">{typeof v === "string" ? v : JSON.stringify(v)}</span>
              </MetaRow>
            ))}
            <MetaRow label="ID">
              <span className="font-mono text-xs text-muted-foreground">{entry.id}</span>
            </MetaRow>
          </dl>

          {attachments.length > 0 && (
            <section aria-labelledby="attachments">
              <h2 id="attachments" className="mb-2 flex items-center gap-1.5 text-sm font-medium">
                <Paperclip className="size-3.5" aria-hidden /> Attachments
              </h2>
              <ul className="space-y-1.5">
                {attachments.map((a) => (
                  <li key={a.id}>
                    <a href={a.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 text-sm hover:underline">
                      {a.mime_type.startsWith("image/") ? (
                        <img src={a.url} alt="" className="size-8 rounded border border-rule object-cover" />
                      ) : (
                        <Paperclip className="size-4 text-muted-foreground" aria-hidden />
                      )}
                      <span className="min-w-0 flex-1 truncate">{a.filename}</span>
                      <span className="text-xs text-muted-foreground">{formatBytes(a.size)}</span>
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <div className="flex flex-col items-start gap-1">
            {entry.revision > 1 && (
              <Button size="sm" variant="ghost" onClick={() => setShowRevisions(true)}>
                <History /> Earlier versions
              </Button>
            )}
            <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive" onClick={() => setConfirmDelete(true)}>
              <Trash2 /> Delete record
            </Button>
          </div>
        </aside>
      </div>

      <RevisionsDialog entry={entry} open={showRevisions} onOpenChange={setShowRevisions} />
      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete record #{entry.sequence}?</AlertDialogTitle>
            <AlertDialogDescription>
              “{entry.title}” disappears from the timeline, search and agent context. Its last version stays in the
              database and can be recovered from the command line.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep record</AlertDialogCancel>
            <AlertDialogAction onClick={() => remove.mutate()} className="bg-destructive text-white hover:bg-destructive/90">
              Delete record
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
