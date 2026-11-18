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

/** How a link reads from its source ("fixes #3") and from its target ("fixed by #7"). */
export const LINK_LABEL: Record<string, { outgoing: string; incoming: string }> = {
  fixes: { outgoing: "Fixes", incoming: "Fixed by" },
  supersedes: { outgoing: "Supersedes", incoming: "Superseded by" },
  relates: { outgoing: "Related to", incoming: "Related to" },
  mentions: { outgoing: "Mentions", incoming: "Mentioned in" },
};

/** Tags are lowercase without spaces; the server validates the rest. */
export function parseTags(text: string): string[] {
  return [...new Set(text.split(/[\s,，]+/).map((t) => t.trim().toLowerCase()).filter(Boolean))].sort();
}

/** `#12`, `12` → `#12`; anything else is returned trimmed (an entry id). */
export function linkTarget(text: string): string {
  const value = text.trim();
  return /^#?\d+$/.test(value) ? `#${value.replace(/^#/, "")}` : value;
}

export const STATUS_LABEL: Record<string, string> = {
  open: "Open",
  resolved: "Resolved",
  obsolete: "Obsolete",
};
