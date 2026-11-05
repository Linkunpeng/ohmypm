import { TYPE_ORDER, typeStyle } from "@/lib/entryTypes";

/**
 * Records per type: a magnitude comparison, so one hue (the primary) and
 * horizontal bars inside a real table — the labels and counts are the data,
 * the bars only make the proportions visible at a glance.
 */
export function TypeDistribution({ counts }: { counts: Record<string, number> }) {
  const types = [...TYPE_ORDER, ...Object.keys(counts).filter((t) => !TYPE_ORDER.includes(t)).sort()];
  const rows = types.map((type) => ({ type, count: counts[type] ?? 0 }));
  const total = rows.reduce((sum, r) => sum + r.count, 0);
  const max = Math.max(1, ...rows.map((r) => r.count));

  if (total === 0) {
    return <p className="text-sm text-muted-foreground">No records yet.</p>;
  }

  return (
    <table className="w-full border-separate border-spacing-y-1.5 text-sm" aria-label="Records per type">
      <thead className="sr-only">
        <tr>
          <th scope="col">Type</th>
          <th scope="col">Share</th>
          <th scope="col">Records</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(({ type, count }) => {
          const share = Math.round((count / total) * 100);
          return (
            <tr key={type} className="group">
              <th scope="row" className="w-24 pr-3 text-left font-normal text-muted-foreground">
                {typeStyle(type).label}
              </th>
              <td className="relative">
                <div className="h-2.5 w-full rounded-sm bg-muted" />
                <div
                  className="absolute inset-y-0 left-0 my-auto h-2.5 rounded-r-[4px] bg-primary/80 transition-colors group-hover:bg-primary"
                  style={{ width: `${(count / max) * 100}%`, minWidth: count ? 4 : 0 }}
                />
                <span
                  role="tooltip"
                  className="pointer-events-none absolute -top-7 left-0 z-10 hidden rounded bg-popover px-2 py-0.5 text-xs whitespace-nowrap text-popover-foreground shadow-sm ring-1 ring-border group-hover:block"
                >
                  {count} {typeStyle(type).label.toLowerCase()} {count === 1 ? "record" : "records"}, {share}%
                </span>
              </td>
              <td className="w-12 pl-3 text-right tabular text-foreground">{count}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
