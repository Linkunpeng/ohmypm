import { useQuery } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { ErrorNotice, Loading, PageHeader } from "@/components/common";
import { MarkdownView } from "@/components/markdown/MarkdownView";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api } from "@/lib/api";
import { useDocumentTitle, useProject } from "@/lib/hooks";

/** Shows exactly what `ohmypm context` gives an agent for this project. */
export function ContextPage() {
  const { projectId = "" } = useParams();
  const [mode, setMode] = useState("brief");
  const [raw, setRaw] = useState(false);
  const { data: project } = useProject(projectId);
  const { data, error, isLoading } = useQuery({
    queryKey: ["context", projectId, mode],
    queryFn: () => api.context(projectId, mode),
  });
  useDocumentTitle("Agent context");

  return (
    <div className="mx-auto max-w-4xl">
      <nav aria-label="Breadcrumb" className="mb-4 text-sm text-muted-foreground">
        <Link to={`/projects/${projectId}`} className="hover:text-foreground hover:underline">
          {project?.name ?? "Project"}
        </Link>
        <span className="mx-1.5">/</span>
        <span>Agent context</span>
      </nav>
      <PageHeader
        title="Agent context"
        actions={
          <Button
            variant="outline"
            size="sm"
            disabled={!data}
            onClick={() => data && navigator.clipboard.writeText(data.markdown).then(() => toast.success("Context copied"))}
          >
            <Copy /> Copy
          </Button>
        }
      >
        What an agent receives from <code className="font-mono">ohmypm context --mode {mode}</code>
        {data && (
          <>
            , about {data.budget.used_tokens} of {data.budget.max_tokens} tokens
            {data.budget.truncated ? ", shortened to fit" : ""}.
          </>
        )}
      </PageHeader>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <ToggleGroup type="single" size="sm" value={mode} onValueChange={(v) => v && setMode(v)} aria-label="Context mode">
          <ToggleGroupItem value="brief" className="px-3">Brief</ToggleGroupItem>
          <ToggleGroupItem value="standard" className="px-3">Standard</ToggleGroupItem>
          <ToggleGroupItem value="full" className="px-3">Full</ToggleGroupItem>
        </ToggleGroup>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" checked={raw} onChange={(e) => setRaw(e.target.checked)} className="accent-[var(--primary)]" />
          Show Markdown source
        </label>
      </div>
      {isLoading ? (
        <Loading />
      ) : error || !data ? (
        <ErrorNotice error={error} what="the context" />
      ) : raw ? (
        <pre className="overflow-x-auto rounded-md border border-rule bg-[var(--code-bg)] p-4 font-mono text-sm whitespace-pre-wrap">
          {data.markdown}
        </pre>
      ) : (
        <div className="rounded-md border border-border bg-card p-6">
          <MarkdownView markdown={data.markdown} />
        </div>
      )}
    </div>
  );
}
