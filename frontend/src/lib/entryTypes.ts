/** Display metadata for entry types. Colors are CSS variables defined in index.css. */
export interface TypeStyle {
  label: string;
  color: string; // CSS color (var)
}

const KNOWN: Record<string, TypeStyle> = {
  milestone: { label: "Milestone", color: "var(--type-milestone)" },
  issue: { label: "Issue", color: "var(--type-issue)" },
  decision: { label: "Decision", color: "var(--type-decision)" },
  knowledge: { label: "Knowledge", color: "var(--type-knowledge)" },
  artifact: { label: "Artifact", color: "var(--type-artifact)" },
  note: { label: "Note", color: "var(--type-note)" },
};

export const TYPE_ORDER = ["milestone", "issue", "decision", "knowledge", "artifact", "note"];

export function typeStyle(type: string): TypeStyle {
  return KNOWN[type] ?? { label: type.charAt(0).toUpperCase() + type.slice(1), color: "var(--type-note)" };
}

export const STATUS_LABEL: Record<string, string> = {
  open: "Open",
  resolved: "Resolved",
  obsolete: "Obsolete",
};
