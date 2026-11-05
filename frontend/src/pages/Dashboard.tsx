import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { TypeTag } from "@/components/Badges";
import { Empty, ErrorNotice, Loading, PageHeader } from "@/components/common";
import { TypeDistribution } from "@/components/TypeDistribution";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { queryKeys, useDocumentTitle } from "@/lib/hooks";

export function Dashboard() {
  useDocumentTitle("Overview");
  const { data, isLoading, error } = useQuery({ queryKey: queryKeys.dashboard, queryFn: api.dashboard });

  if (isLoading) return <Loading />;
  if (error) return <ErrorNotice error={error} what="the overview" />;
  if (!data) return null;

  if (data.projects.length === 0) {
    return (
      <div className="mx-auto max-w-2xl pt-10">
        <PageHeader title="No projects yet" />
        <div className="space-y-4 text-[0.95rem] leading-relaxed">
          <p>ohmypm keeps development records for projects you register on this machine. Nothing is written into the project itself.</p>
          <pre className="rounded-md border border-rule bg-[var(--code-bg)] p-4 font-mono text-sm">
            {"cd ~/Projects/your-project\nohmypm register\nohmypm agents install   # let your coding agents use it"}
          </pre>
          <p className="text-muted-foreground">Reload this page after registering.</p>
        </div>
      </div>
    );
  }

  const recentProjects = data.projects.slice(0, 6);

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Overview">
        {data.projects.length} {data.projects.length === 1 ? "project" : "projects"}, {data.total_entries}{" "}
        {data.total_entries === 1 ? "record" : "records"} on this machine
      </PageHeader>

      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <section aria-labelledby="recent-records">
          <h2 id="recent-records" className="mb-3 text-sm font-medium text-muted-foreground">
            Latest records
          </h2>
          {data.recent_entries.length === 0 ? (
            <Empty title="No records yet">Agents and you add records with <code>ohmypm log add</code>.</Empty>
          ) : (
            <ol className="divide-y divide-rule border-y border-rule">
              {data.recent_entries.map((e) => (
                <li key={e.id}>
                  <Link
                    to={`/projects/${e.project_id}/entries/${e.id}`}
                    className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-x-3 py-3 hover:bg-accent/50 sm:grid-cols-[3.5rem_minmax(0,1fr)_9rem]"
                  >
                    <span className="pt-0.5 text-right tabular text-sm text-muted-foreground">#{e.sequence}</span>
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{e.title}</span>
                      <span className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
                        <TypeTag type={e.type} />
                        <span>{e.project_name}</span>
                        {e.author && <span>by {e.author}</span>}
                      </span>
                    </span>
                    <span className="hidden pt-0.5 text-right text-xs text-muted-foreground sm:block">
                      {timeAgo(e.created_at)}
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
          )}
        </section>

        <aside className="space-y-10">
          <section aria-labelledby="active-projects">
            <h2 id="active-projects" className="mb-3 text-sm font-medium text-muted-foreground">
              Recently active
            </h2>
            <ul className="space-y-3">
              {recentProjects.map((p) => (
                <li key={p.id}>
                  <Link to={`/projects/${p.id}`} className="group block">
                    <span className="font-medium group-hover:text-primary">{p.name}</span>
                    <span className="block truncate font-mono text-xs text-muted-foreground" title={p.root_path}>
                      {p.root_path}
                    </span>
                    <span className="block text-xs text-muted-foreground">
                      {p.entry_count} records, active {timeAgo(p.last_activity_at ?? p.created_at)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="by-type">
            <h2 id="by-type" className="mb-2 text-sm font-medium text-muted-foreground">
              Records by type
            </h2>
            <TypeDistribution counts={data.type_counts} />
          </section>

          {data.recent_summaries.length > 0 && (
            <section aria-labelledby="summaries">
              <h2 id="summaries" className="mb-3 text-sm font-medium text-muted-foreground">
                Recently updated summaries
              </h2>
              <ul className="space-y-3">
                {data.recent_summaries.map((s) => (
                  <li key={s.project_id}>
                    <Link to={`/projects/${s.project_id}/summary`} className="group block">
                      <span className="font-medium group-hover:text-primary">{s.project_name}</span>
                      <span className="block text-xs text-muted-foreground">
                        {timeAgo(s.updated_at)}
                        {s.updated_by ? ` by ${s.updated_by}` : ""}
                      </span>
                      {s.excerpt && <span className="mt-1 line-clamp-2 block text-sm text-foreground/80">{s.excerpt}</span>}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
