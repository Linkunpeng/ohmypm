"""Similar records: deterministic duplicate and follow-up detection (no AI).

Titles and bodies are split into terms (Latin words / version strings and CJK
character bigrams) and compared with TF-IDF cosine similarity. Document
frequencies come from the project's own records, so terms that appear
everywhere in a project (a device id, the product name) weigh little. Shared
tags add to the score. The score is a weighted average of the parts that the
query actually has (a bare title is compared by title only).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ohmypm.storage.models import Entry, EntryLink, Project

WEIGHTS = {"title": 0.55, "body": 0.3, "tags": 0.15}
DEFAULT_MIN_SCORE = 0.25
MAX_BODY_CHARS = 6000
MAX_CANDIDATES = 2000

# Letters of CJK scripts (no punctuation or full-width forms).
_CJK_RUN = re.compile(
    "[\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]+"
)
# Latin words, numbers, versions and identifiers such as "v3.5.0" or "device:a0ac1".
_WORD = re.compile(r"[a-z0-9]+(?:[._:/+-][a-z0-9]+)*")


def terms(text: str) -> Counter[str]:
    """Term counts of ``text``: Latin tokens (2+ chars) and CJK bigrams."""
    text = text.lower()
    counts: Counter[str] = Counter(w for w in _WORD.findall(text) if len(w) > 1)
    for run in _CJK_RUN.findall(text):
        if len(run) == 1:
            counts[run] += 1
        else:
            counts.update(run[i : i + 2] for i in range(len(run) - 1))
    return counts


class _Idf:
    def __init__(self, documents: Iterable[Counter[str]]) -> None:
        df: Counter[str] = Counter()
        n = 0
        for doc in documents:
            df.update(doc.keys())
            n += 1
        self._df = df
        self._n = n

    def __getitem__(self, term: str) -> float:
        return math.log((self._n + 1) / (self._df.get(term, 0) + 1)) + 1.0


def _vector(counts: Counter[str], idf: _Idf) -> dict[str, float]:
    return {t: (1.0 + math.log(c)) * idf[t] for t, c in counts.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    dot = sum(w * b.get(t, 0.0) for t, w in a.items())
    norm = math.sqrt(sum(w * w for w in a.values())) * math.sqrt(sum(w * w for w in b.values()))
    return dot / norm if norm else 0.0


def coverage(query: dict[str, float], doc: dict[str, float]) -> float:
    """Share of the query's term weight found in ``doc`` (a short draft vs. a long record)."""
    total = sum(query.values())
    return sum(w for t, w in query.items() if t in doc) / total if total else 0.0


@dataclass
class Match:
    entry: Entry
    score: float
    title_score: float
    body_score: float | None
    shared_tags: list[str]
    linked: bool


def _linked_ids(session: Session, entry_id: str) -> set[str]:
    rows = session.execute(
        select(EntryLink.source_id, EntryLink.target_id).where(
            (EntryLink.source_id == entry_id) | (EntryLink.target_id == entry_id)
        )
    ).all()
    return {other for pair in rows for other in pair if other != entry_id}


def find_similar(
    session: Session,
    project: Project,
    *,
    title: str,
    content: str = "",
    tags: Sequence[str] = (),
    exclude: Entry | None = None,
    types: Sequence[str] | None = None,
    statuses: Sequence[str] | None = None,
    include_obsolete: bool = False,
    limit: int = 5,
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[Match]:
    """Records of ``project`` similar to the given title/body/tags, best first."""
    stmt = select(Entry).where(Entry.project_id == project.id)
    if exclude is not None:
        stmt = stmt.where(Entry.id != exclude.id)
    if types:
        stmt = stmt.where(Entry.type.in_(types))
    if statuses:
        stmt = stmt.where(Entry.status.in_(statuses))
    elif not include_obsolete:
        stmt = stmt.where((Entry.status.is_(None)) | (Entry.status != "obsolete"))
    candidates = list(session.scalars(stmt.order_by(Entry.sequence.desc()).limit(MAX_CANDIDATES)).all())
    if not candidates:
        return []

    # Document frequencies over the whole project, not just the filtered
    # candidates, so a narrow filter does not make common terms look rare.
    corpus = list(
        session.execute(
            select(Entry.title, Entry.content).where(Entry.project_id == project.id).limit(MAX_CANDIDATES)
        ).all()
    )
    title_terms = [terms(t) for t, _ in corpus]
    body_terms = [terms(c[:MAX_BODY_CHARS]) for _, c in corpus]
    title_idf = _Idf(title_terms)
    body_idf = _Idf(body_terms)

    query_title = _vector(terms(title), title_idf)
    query_body = _vector(terms(content[:MAX_BODY_CHARS]), body_idf) if content.strip() else None
    query_tags = set(tags)
    weights = {}
    if query_title:
        weights["title"] = WEIGHTS["title"]
    if query_body:
        weights["body"] = WEIGHTS["body"]
    if query_tags:
        weights["tags"] = WEIGHTS["tags"]
    total = sum(weights.values())
    if not total:
        return []
    linked = _linked_ids(session, exclude.id) if exclude is not None else set()

    matches = []
    for entry in candidates:
        title_score = cosine(query_title, _vector(terms(entry.title), title_idf))
        body_score = None
        if query_body:
            body_score = coverage(query_body, _vector(terms(entry.content[:MAX_BODY_CHARS]), body_idf))
        shared = sorted(query_tags & set(entry.tags or []))
        tag_score = len(shared) / len(query_tags | set(entry.tags or [])) if query_tags else 0.0
        score = (
            weights.get("title", 0.0) * title_score
            + weights.get("body", 0.0) * (body_score or 0.0)
            + weights.get("tags", 0.0) * tag_score
        ) / total
        if score >= min_score:
            matches.append(Match(entry, score, title_score, body_score, shared, entry.id in linked))
    matches.sort(key=lambda m: (-m.score, -m.entry.sequence))
    return matches[:limit]


def to_out(match: Match) -> dict[str, object]:
    e = match.entry
    return {
        "entry_id": e.id,
        "sequence": e.sequence,
        "type": e.type,
        "title": e.title,
        "status": e.status,
        "created_at": e.created_at,
        "updated_at": e.updated_at,
        "tags": list(e.tags or []),
        "score": round(match.score, 3),
        "title_score": round(match.title_score, 3),
        "body_score": None if match.body_score is None else round(match.body_score, 3),
        "shared_tags": match.shared_tags,
        "linked": match.linked,
    }
