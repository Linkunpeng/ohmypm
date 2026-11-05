"""Full-text search over projects, entries and summaries (SQLite FTS5).

The index uses the ``trigram`` tokenizer, so any substring of three or more
characters matches - this handles Chinese, Japanese and identifiers such as
``cv::Mat`` without word segmentation. Shorter terms (e.g. two-character
Chinese words such as "相机") fall back to a LIKE scan of the same table.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ohmypm.core.entries import like_escape
from ohmypm.core.errors import ValidationError
from ohmypm.core.schemas import SearchHit

KINDS = ("entry", "summary", "project")
MAX_LIMIT = 200
SNIPPET_RADIUS = 80


def split_terms(query: str) -> list[str]:
    try:
        terms = shlex.split(query)
    except ValueError:
        terms = query.split()
    return [t for t in (term.strip() for term in terms) if t]


def _db_time(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def _parse_db_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=UTC)
    except ValueError:
        return None


def make_snippet(title: str, body: str, terms: Sequence[str], radius: int = SNIPPET_RADIUS) -> str:
    flat = " ".join((body or "").split())
    lowered = flat.lower()
    positions = [lowered.find(t.lower()) for t in terms]
    positions = [p for p in positions if p >= 0]
    if not positions:
        return flat[: radius * 2] + ("…" if len(flat) > radius * 2 else "")
    start = max(0, min(positions) - radius)
    end = min(len(flat), min(positions) + radius)
    return ("…" if start else "") + flat[start:end] + ("…" if end < len(flat) else "")


def search(
    session: Session,
    query: str,
    *,
    project_ids: Sequence[str] | None = None,
    kinds: Sequence[str] | None = None,
    entry_types: Sequence[str] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    include_archived: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[SearchHit], int]:
    terms = split_terms(query)
    if not terms:
        raise ValidationError("Search query must not be empty")
    if not 1 <= limit <= MAX_LIMIT:
        raise ValidationError(f"limit must be between 1 and {MAX_LIMIT}")
    if offset < 0:
        raise ValidationError("offset must be >= 0")
    kinds = list(kinds) if kinds else list(KINDS)
    for kind in kinds:
        if kind not in KINDS:
            raise ValidationError(f"Unknown search kind '{kind}'", details={"allowed": list(KINDS)})

    # The FTS table is referenced by its own name (no alias) so MATCH and the
    # bm25() auxiliary function resolve correctly.
    s = "search_index"
    params: dict[str, Any] = {}
    where = []
    long_terms = [t for t in terms if len(t) >= 3]
    short_terms = [t for t in terms if len(t) < 3]
    if long_terms:
        params["fts"] = " ".join('"' + t.replace('"', '""') + '"' for t in long_terms)
        where.append(f"{s} MATCH :fts")
    for i, term in enumerate(short_terms):
        params[f"like{i}"] = f"%{like_escape(term)}%"
        where.append(f"({s}.title LIKE :like{i} ESCAPE '\\' OR {s}.body LIKE :like{i} ESCAPE '\\')")

    def in_clause(column: str, prefix: str, values: Sequence[str]) -> str:
        keys = []
        for i, value in enumerate(values):
            params[f"{prefix}{i}"] = value
            keys.append(f":{prefix}{i}")
        return f"{column} IN ({', '.join(keys)})"

    where.append(in_clause(f"{s}.kind", "kind", kinds))
    if project_ids is not None:
        if not project_ids:
            return [], 0
        where.append(in_clause(f"{s}.project_id", "pid", project_ids))
    if entry_types:
        where.append(f"({s}.kind != 'entry' OR {in_clause(f'{s}.entry_type', 'et', entry_types)})")
    if since is not None:
        params["since"] = _db_time(since)
        where.append(f"{s}.created_at >= :since")
    if until is not None:
        params["until"] = _db_time(until)
        where.append(f"{s}.created_at <= :until")
    if not include_archived:
        where.append("p.archived_at IS NULL")

    from_sql = (
        f"FROM {s} JOIN projects AS p ON p.id = {s}.project_id "
        f"LEFT JOIN entries AS e ON {s}.kind = 'entry' AND e.id = {s}.ref_id "
        f"WHERE {' AND '.join(where)}"
    )
    # Title matches weigh more than body matches.
    score = f"bm25({s}, 0, 0, 0, 0, 0, 8.0, 1.0)" if long_terms else "0"
    order = f"{score}, {s}.created_at DESC" if long_terms else f"{s}.created_at DESC"

    total = session.execute(text(f"SELECT count(*) {from_sql}"), params).scalar_one()
    rows = session.execute(
        text(
            f"SELECT {s}.kind, {s}.ref_id, {s}.project_id, {s}.entry_type, {s}.created_at, "
            f"{s}.title, {s}.body, p.name, e.sequence, {score} AS score "
            f"{from_sql} ORDER BY {order} LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    ).all()

    hits = [
        SearchHit(
            kind=row[0],
            ref_id=row[1],
            project_id=row[2],
            entry_type=row[3],
            created_at=_parse_db_time(row[4]),
            title=row[5],
            snippet=make_snippet(row[5], row[6], terms),
            project_name=row[7],
            sequence=row[8],
            score=round(-float(row[9]), 4) if long_terms else None,
        )
        for row in rows
    ]
    return hits, int(total)
