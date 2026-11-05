"""Deterministic text helpers: excerpts, token estimates, Markdown truncation."""

from __future__ import annotations

import math
import re

ASSET_SCHEME = "ohmypm-asset://"
ASSET_REF_RE = re.compile(
    r"ohmypm-asset://([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)

_CJK_RE = re.compile(
    "[\u1100-\u11ff\u2e80-\u2fdf\u3000-\u303f\u3040-\u30ff\u3100-\u312f\u3130-\u318f"
    "\u31a0-\u31bf\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]"
)
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")

_MD_NOISE = [
    (re.compile(r"```mermaid.*?```", re.S), " [diagram] "),
    (re.compile(r"```.*?```", re.S), " [code] "),
    (re.compile(r"(?:^\s*\|.*\|\s*$\n?)+", re.M), " [table] "),
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"[image: \1]"),
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
    (re.compile(r"^\s{0,3}#{1,6}\s*", re.M), ""),
    (re.compile(r"^\s{0,3}>\s?", re.M), ""),
    (re.compile(r"^\s*[-*+]\s+\[[ xX]\]\s+", re.M), "• "),
    (re.compile(r"^\s*[-*+]\s+", re.M), "• "),
    (re.compile(r"(\*\*|__)(.+?)\1"), r"\2"),
    (re.compile(r"`([^`]+)`"), r"\1"),
    (re.compile(r"\$\$.*?\$\$", re.S), " [math] "),
]


def estimate_tokens(text: str) -> int:
    """Rough, deterministic token estimate.

    CJK characters count as one token each, everything else as ~4 chars per
    token. Good enough for budgeting context; no tokenizer dependency.
    """
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    return cjk + math.ceil((len(text) - cjk) / 4)


def excerpt(markdown: str, limit: int = 200) -> str:
    """Single-line plain-text preview of a Markdown document."""
    text = markdown
    for pattern, repl in _MD_NOISE:
        text = pattern.sub(repl, text)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip() + "…"


def truncate_markdown(text: str, max_tokens: int, *, notice: str | None = None) -> tuple[str, bool]:
    """Cut ``text`` to roughly ``max_tokens``, preferring line boundaries.

    Never leaves a code fence open. Returns ``(text, was_truncated)``; when
    truncated, a visible omission marker is appended.
    """
    if max_tokens <= 0:
        return "", bool(text)
    if estimate_tokens(text) <= max_tokens:
        return text, False

    lines = text.split("\n")
    kept: list[str] = []
    used = 0
    fence: str | None = None
    for line in lines:
        cost = estimate_tokens(line) + 1
        if used + cost > max_tokens:
            if not kept:
                # A single huge first line: cut it by characters.
                ratio = max_tokens / max(cost, 1)
                kept.append(line[: max(1, int(len(line) * ratio) - 1)])
            break
        kept.append(line)
        used += cost
        match = _FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker[0] * 3
            elif marker.startswith(fence):
                fence = None
    # Drop a trailing dangling heading or empty lines.
    while kept and (not kept[-1].strip() or kept[-1].lstrip().startswith("#")):
        kept.pop()
    if fence is not None:
        kept.append(fence)
    omitted = len(text) - sum(len(line) + 1 for line in kept)
    marker = notice or f"… [truncated: about {max(omitted, 0)} more characters omitted]"
    kept.append("")
    kept.append(marker)
    return "\n".join(kept), True


_HEADING_RE = re.compile(r"^(\s{0,3})(#{1,6})(\s)")


def demote_headings(markdown: str, levels: int) -> str:
    """Shift ATX headings down by ``levels`` (capped at h6), skipping code fences.

    Used when embedding a document under a heading of another document.
    """
    out = []
    fence: str | None = None
    for line in markdown.split("\n"):
        match = _FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker[0] * 3
            elif marker.startswith(fence):
                fence = None
        elif fence is None:
            line = _HEADING_RE.sub(
                lambda m: m.group(1) + "#" * min(6, len(m.group(2)) + levels) + m.group(3), line
            )
        out.append(line)
    return "\n".join(out)


def asset_refs(markdown: str) -> set[str]:
    return {m.lower() for m in ASSET_REF_RE.findall(markdown or "")}
