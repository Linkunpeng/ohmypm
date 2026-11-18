import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers, Link2, Plus, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { StatusTag } from "@/components/Badges";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { LINK_LABEL, linkTarget } from "@/lib/entryTypes";
import { queryKeys, useAuthor } from "@/lib/hooks";
import type { Entry, EntryLink, ExplicitLinkKind, LinkInput } from "@/lib/types";

const KIND_HELP: Record<ExplicitLinkKind, string> = {
  relates: "Related to",
  fixes: "Fixes (resolves the open issue)",
  supersedes: "Supersedes (marks it obsolete)",
};

function useLinkMutation(entry: Entry) {
  const client = useQueryClient();
  const [author] = useAuthor();
  return useMutation({
    mutationFn: (changes: { add_links?: LinkInput[]; remove_links?: string[] }) =>
      api.updateEntry(entry.id, { ...changes, author }),
    onSuccess: ({ entry: updated }, changes) => {
      client.setQueryData(queryKeys.entry(entry.id), updated);
      // The other record's backlinks (and maybe its status) changed too.
      void client.invalidateQueries({ queryKey: ["entry"] });
      void client.invalidateQueries({ queryKey: queryKeys.entries(entry.project_id) });
      void client.invalidateQueries({ queryKey: ["similar", entry.id] });
      if (changes.remove_links?.length) {
        toast.success(`Link to ${changes.remove_links[0]} removed. Its status is unchanged.`);
      } else {
        const added = changes.add_links?.[0];
        const note = added?.kind === "fixes" ? " and marked it resolved" : added?.kind === "supersedes" ? " and marked it obsolete" : "";
        toast.success(`Linked to ${added?.target}${note}`);
      }
    },
    onError: (err) => toast.error(err.message),
  });
}

function AddLinkForm({ entry, onDone }: { entry: Entry; onDone: () => void }) {
  const [kind, setKind] = useState<ExplicitLinkKind>("relates");
  const [target, setTarget] = useState("");
  const mutation = useLinkMutation(entry);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const ref = linkTarget(target);
    if (!ref) return;
    mutation.mutate({ add_links: [{ target: ref, kind }] }, { onSuccess: () => { setTarget(""); onDone(); } });
  };
  return (
    <form onSubmit={submit} className="mt-3 space-y-2" aria-label="Add a link">
      <select
        aria-label="Link kind"
        value={kind}
        onChange={(e) => setKind(e.target.value as ExplicitLinkKind)}
        className="h-8 w-full rounded-md border border-input bg-card px-2 text-sm"
      >
        {(Object.keys(KIND_HELP) as ExplicitLinkKind[]).map((k) => (
          <option key={k} value={k}>
            {KIND_HELP[k]}
          </option>
        ))}
      </select>
      <div className="flex gap-2">
        <Input
          aria-label="Target record"
          placeholder="#12"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          className="h-8"
        />
        <Button type="submit" size="sm" disabled={!target.trim() || mutation.isPending}>
          Link
        </Button>
      </div>
    </form>
  );
}

/** Links grouped by how they read from this record ("Fixes", "Mentioned in", …); explicit links are editable. */
export function Relations({ entry, projectId }: { entry: Entry; projectId: string }) {
  const [adding, setAdding] = useState(false);
  const mutation = useLinkMutation(entry);
  const groups = new Map<string, { link: EntryLink; removable: boolean }[]>();
  const add = (links: EntryLink[] | null | undefined, direction: "outgoing" | "incoming") => {
    for (const link of links ?? []) {
      const label = LINK_LABEL[link.kind]?.[direction] ?? link.kind;
      const group = groups.get(label) ?? [];
      if (!group.some((g) => g.link.entry_id === link.entry_id)) {
        groups.set(label, [...group, { link, removable: direction === "outgoing" && link.kind !== "mentions" }]);
      }
    }
  };
  add(entry.links, "outgoing");
  add(entry.backlinks, "incoming");
  return (
    <section aria-labelledby="relations">
      <div className="mb-2 flex items-center justify-between">
        <h2 id="relations" className="flex items-center gap-1.5 text-sm font-medium">
          <Link2 className="size-3.5" aria-hidden /> Related records
        </h2>
        <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => setAdding((v) => !v)} aria-expanded={adding} aria-label="Add a link">
          <Plus /> Link
        </Button>
      </div>
      {groups.size === 0 && !adding && <p className="text-sm text-muted-foreground">No links yet. Writing #N in the body also links.</p>}
      <div className="space-y-3">
        {[...groups].map(([label, items]) => (
          <div key={label}>
            <h3 className="mb-1 text-xs text-muted-foreground">{label}</h3>
            <ul className="space-y-1">
              {items.map(({ link, removable }) => (
                <li key={link.entry_id} className="group flex items-start gap-1 text-sm">
                  <span className="min-w-0 flex-1">
                    <Link to={`/projects/${projectId}/entries/${link.entry_id}`} className="hover:underline">
                      <span className="tabular text-muted-foreground">{link.sequence}</span>{" "}
                      <span className={link.status === "obsolete" ? "text-muted-foreground line-through" : ""}>{link.title}</span>
                    </Link>{" "}
                    <StatusTag status={link.status} />
                  </span>
                  {removable && (
                    <button
                      type="button"
                      className="rounded p-0.5 text-muted-foreground opacity-60 hover:bg-accent hover:text-foreground group-hover:opacity-100"
                      aria-label={`Remove link to #${link.sequence}`}
                      title="Remove link (statuses are not changed)"
                      disabled={mutation.isPending}
                      onClick={() => mutation.mutate({ remove_links: [`#${link.sequence}`] })}
                    >
                      <X className="size-3.5" aria-hidden />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      {adding && <AddLinkForm entry={entry} onDone={() => setAdding(false)} />}
    </section>
  );
}

/** Records with a similar title, body or tags: candidates for a link or a merge. */
export function SimilarRecords({ entry, projectId }: { entry: Entry; projectId: string }) {
  const { data } = useQuery({
    queryKey: ["similar", entry.id, entry.revision],
    queryFn: () => api.similar(entry.id, { limit: 5 }),
  });
  const mutation = useLinkMutation(entry);
  if (!data?.length) return null;
  return (
    <section aria-labelledby="similar">
      <h2 id="similar" className="mb-2 flex items-center gap-1.5 text-sm font-medium">
        <Layers className="size-3.5" aria-hidden /> Similar records
      </h2>
      <ul className="space-y-1.5">
        {data.map((hit) => (
          <li key={hit.entry_id} className="flex items-start gap-2 text-sm">
            <span className="w-8 shrink-0 pt-0.5 text-right text-xs tabular text-muted-foreground" title="Similarity">
              {Math.round(hit.score * 100)}%
            </span>
            <span className="min-w-0 flex-1">
              <Link to={`/projects/${projectId}/entries/${hit.entry_id}`} className="hover:underline">
                <span className="tabular text-muted-foreground">{hit.sequence}</span> {hit.title}
              </Link>{" "}
              <StatusTag status={hit.status} />
            </span>
            {hit.linked ? (
              <span className="pt-0.5 text-xs text-muted-foreground">linked</span>
            ) : (
              <button
                type="button"
                className="rounded px-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
                aria-label={`Link #${hit.sequence} as related`}
                disabled={mutation.isPending}
                onClick={() => mutation.mutate({ add_links: [{ target: `#${hit.sequence}`, kind: "relates" }] })}
              >
                Link
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
