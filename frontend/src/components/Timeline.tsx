import { Link } from "react-router";

import { StatusTag, TypeTag } from "@/components/Badges";
import { dayKey, formatDate, formatTime } from "@/lib/format";
import { typeStyle } from "@/lib/entryTypes";
import type { Asset, Entry } from "@/lib/types";

/**
 * The logbook: each record sits on a ruled line with its sequence number in
 * the left margin, a type-colored mark on the rail and the day as a running head.
 */
export function Timeline({
  entries,
  projectId,
  assets,
}: {
  entries: Entry[];
  projectId: string;
  assets: Map<string, Asset>;
}) {
  const groups: { day: string; label: string; items: Entry[] }[] = [];
  for (const entry of entries) {
    const day = dayKey(entry.created_at);
    const last = groups.at(-1);
    if (last?.day === day) last.items.push(entry);
    else groups.push({ day, label: formatDate(entry.created_at), items: [entry] });
  }

  return (
    <div className="relative">
      {groups.map((group) => (
        <section key={group.day} aria-label={group.label} className="relative">
          <h3 className="sticky top-0 z-10 grid grid-cols-[4.5rem_1.25rem_minmax(0,1fr)] bg-background/95 py-2 backdrop-blur-sm">
            <span />
            <span />
            <span className="text-sm font-medium text-muted-foreground">{group.label}</span>
          </h3>
          <ol>
            {group.items.map((entry) => (
              <TimelineRow key={entry.id} entry={entry} projectId={projectId} assets={assets} />
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}

function TimelineRow({ entry, projectId, assets }: { entry: Entry; projectId: string; assets: Map<string, Asset> }) {
  const images = entry.asset_ids.map((id) => assets.get(id)).filter((a): a is Asset => !!a && a.mime_type.startsWith("image/"));
  const color = typeStyle(entry.type).color;
  const muted = entry.status === "obsolete";

  return (
    <li className="group grid grid-cols-[4.5rem_1.25rem_minmax(0,1fr)]">
      {/* margin: sequence number and time */}
      <div className="pt-3 pr-3 text-right">
        <Link
          to={`/projects/${projectId}/entries/${entry.id}`}
          className="block text-[1.05rem] font-medium tabular leading-tight text-foreground/70 group-hover:text-primary"
          aria-label={`Record ${entry.sequence}`}
        >
          {entry.sequence}
        </Link>
        <time dateTime={entry.created_at} className="block text-xs tabular text-muted-foreground">
          {formatTime(entry.created_at)}
        </time>
      </div>
      {/* rail */}
      <div className="relative flex justify-center" aria-hidden>
        <span className="absolute inset-y-0 w-px bg-rule" />
        <span
          className="relative mt-[1.1rem] size-2.5 rounded-[3px] ring-4 ring-background"
          style={{ background: muted ? "var(--muted-foreground)" : color }}
        />
      </div>
      {/* record */}
      <div className="min-w-0 border-b border-rule py-3 pl-3">
        <Link
          to={`/projects/${projectId}/entries/${entry.id}`}
          className={`block text-[1.02rem] leading-snug font-medium text-pretty hover:text-primary ${muted ? "text-muted-foreground line-through decoration-1" : ""}`}
        >
          {entry.title}
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <TypeTag type={entry.type} />
          <StatusTag status={entry.status} />
          {entry.author && <span>{entry.author}</span>}
          {entry.revision > 1 && <span>edited</span>}
        </div>
        {entry.excerpt && (
          <p className="mt-1.5 line-clamp-2 max-w-[72ch] font-serif text-[0.95rem] leading-relaxed text-foreground/75">
            {entry.excerpt}
          </p>
        )}
        {images.length > 0 && (
          <div className="mt-2 flex gap-2">
            {images.slice(0, 4).map((a) => (
              <img
                key={a.id}
                src={a.url}
                alt={a.filename}
                loading="lazy"
                className="h-14 w-20 rounded border border-rule object-cover"
              />
            ))}
            {images.length > 4 && (
              <span className="self-center text-xs text-muted-foreground">+{images.length - 4}</span>
            )}
          </div>
        )}
      </div>
    </li>
  );
}
