const ASSET_PREFIX = "ohmypm-asset://";
const ASSET_ID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

/** Map `ohmypm-asset://<id>` to the local API URL; other URLs are returned unchanged. */
export function assetUrl(src: string): string {
  if (src.startsWith(ASSET_PREFIX)) {
    const id = src.slice(ASSET_PREFIX.length);
    return ASSET_ID.test(id) ? `/api/assets/${id.toLowerCase()}` : "";
  }
  return src;
}

/** The inverse, used when an image is inserted from an uploaded asset URL. */
export function assetUri(id: string): string {
  return `${ASSET_PREFIX}${id}`;
}

const SAFE_PROTOCOL = /^(https?|mailto|ohmypm-asset):/i;

/** react-markdown URL policy: allow http(s), mailto, ohmypm assets and relative links. */
export function safeUrl(url: string): string {
  const trimmed = url.trim();
  if (trimmed.startsWith(ASSET_PREFIX)) return assetUrl(trimmed);
  if (/^[a-z][a-z0-9+.-]*:/i.test(trimmed) && !SAFE_PROTOCOL.test(trimmed)) return "";
  return trimmed;
}

const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const dateOnly = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const timeOnly = new Intl.DateTimeFormat(undefined, { timeStyle: "short" });
const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

export function formatDateTime(value: string | null | undefined): string {
  return value ? dateTime.format(new Date(value)) : "—";
}

export function formatDate(value: string | null | undefined): string {
  return value ? dateOnly.format(new Date(value)) : "—";
}

export function formatTime(value: string): string {
  return timeOnly.format(new Date(value));
}

export function dayKey(value: string): string {
  const d = new Date(value);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function timeAgo(value: string | null | undefined, now: Date = new Date()): string {
  if (!value) return "never";
  const seconds = (new Date(value).getTime() - now.getTime()) / 1000;
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31536000],
    ["month", 2592000],
    ["week", 604800],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return relative.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
}
