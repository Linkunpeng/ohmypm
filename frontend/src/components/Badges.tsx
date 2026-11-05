import { STATUS_LABEL, typeStyle } from "@/lib/entryTypes";
import { cn } from "@/lib/utils";

/** Entry type: a small colored square plus the name (identity is never color alone). */
export function TypeTag({ type, className }: { type: string; className?: string }) {
  const style = typeStyle(type);
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", className)}>
      <span aria-hidden className="size-2 rounded-[2px]" style={{ background: style.color }} />
      <span className="text-foreground/80">{style.label}</span>
    </span>
  );
}

export function StatusTag({ status }: { status: string | null }) {
  if (!status) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-px text-xs",
        status === "open" && "border-[color:var(--type-issue)] text-[color:var(--type-issue)]",
        status === "resolved" && "border-[color:var(--type-milestone)] text-[color:var(--type-milestone)]",
        status === "obsolete" && "border-border text-muted-foreground line-through",
      )}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}
