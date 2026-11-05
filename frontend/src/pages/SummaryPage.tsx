import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { ErrorNotice, Loading, PageHeader } from "@/components/common";
import { MarkdownEditor, type EditorMode } from "@/components/editor/MarkdownEditor";
import { MarkdownView } from "@/components/markdown/MarkdownView";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { queryKeys, useAuthor, useDocumentTitle, useProject } from "@/lib/hooks";
import { SUMMARY_SECTIONS, type Summary, type SummarySection } from "@/lib/types";

const SECTION_INFO: Record<SummarySection, { title: string; hint: string }> = {
  overview: { title: "Overview", hint: "What the project is and what it is for." },
  architecture: { title: "Architecture", hint: "Main components, technologies and how they fit together." },
  current_state: { title: "Current state", hint: "What works today and what is in progress." },
  important_decisions: { title: "Important decisions", hint: "Settled technical choices and why." },
  known_issues: { title: "Known issues", hint: "Problems that are not solved yet." },
  next_steps: { title: "Next steps", hint: "What should happen next." },
};

function SectionEditor({
  projectId,
  section,
  summary,
  onDone,
}: {
  projectId: string;
  section: SummarySection;
  summary: Summary;
  onDone: () => void;
}) {
  const client = useQueryClient();
  const [author] = useAuthor();
  const [value, setValue] = useState(summary[section]);
  const [mode, setMode] = useState<EditorMode>("rich");
  const [notice, setNotice] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => api.saveSummary(projectId, { [section]: value }, summary.revision, author),
    onSuccess: ({ summary: updated, changed }) => {
      client.setQueryData(queryKeys.summary(projectId), updated);
      void client.invalidateQueries({ queryKey: queryKeys.dashboard });
      toast.success(changed ? `${SECTION_INFO[section].title} saved` : "No changes");
      onDone();
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError && err.code === "conflict"
          ? "The summary was changed elsewhere meanwhile. Reload the page and apply your edit again."
          : err.message,
      ),
  });
  return (
    <div className="space-y-3">
      {notice && <p className="rounded-md bg-accent px-3 py-2 text-sm">{notice}</p>}
      <MarkdownEditor
        value={value}
        onChange={setValue}
        projectId={projectId}
        mode={mode}
        onModeChange={setMode}
        minHeight={220}
        onLossyRichText={(reason) => {
          setMode("markdown");
          setNotice(reason);
        }}
        placeholder={SECTION_INFO[section].hint}
      />
      <div className="flex gap-2">
        <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
          Save section
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

export function SummaryPage() {
  const { projectId = "" } = useParams();
  const { data: project } = useProject(projectId);
  const [editing, setEditing] = useState<SummarySection | null>(null);
  const { data: summary, error, isLoading } = useQuery({
    queryKey: queryKeys.summary(projectId),
    queryFn: () => api.summary(projectId),
  });
  useDocumentTitle(project ? `${project.name} summary` : "Summary");

  if (isLoading) return <Loading />;
  if (error || !summary) return <ErrorNotice error={error} what="the summary" />;

  return (
    <div className="mx-auto max-w-4xl">
      <nav aria-label="Breadcrumb" className="mb-4 text-sm text-muted-foreground">
        <Link to={`/projects/${projectId}`} className="hover:text-foreground hover:underline">
          {project?.name ?? "Project"}
        </Link>
        <span className="mx-1.5">/</span>
        <span>Summary</span>
      </nav>
      <PageHeader title="Project summary">
        {summary.updated_at ? (
          <>
            Revision {summary.revision}, updated {formatDateTime(summary.updated_at)}
            {summary.updated_by ? ` by ${summary.updated_by}` : ""}. Agents read this first.
          </>
        ) : (
          "Not written yet. Agents read this first, so keep it short and current."
        )}
      </PageHeader>

      <div className="divide-y divide-rule border-y border-rule">
        {SUMMARY_SECTIONS.map((section) => (
          <section key={section} aria-labelledby={`sec-${section}`} className="py-6">
            <div className="mb-2 flex items-baseline justify-between gap-4">
              <h2 id={`sec-${section}`} className="text-lg font-semibold">
                {SECTION_INFO[section].title}
              </h2>
              {editing !== section && (
                <Button size="sm" variant="ghost" onClick={() => setEditing(section)} aria-label={`Edit ${SECTION_INFO[section].title}`}>
                  <Pencil /> Edit
                </Button>
              )}
            </div>
            {editing === section ? (
              <SectionEditor
                key={summary.revision}
                projectId={projectId}
                section={section}
                summary={summary}
                onDone={() => setEditing(null)}
              />
            ) : summary[section] ? (
              <MarkdownView markdown={summary[section]} className="max-w-[76ch]" />
            ) : (
              <p className="text-sm text-muted-foreground">{SECTION_INFO[section].hint}</p>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
