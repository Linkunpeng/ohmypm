"""ContextBuilder: deterministic, budgeted project context for agents.

No AI is involved. The builder selects stored information by fixed rules,
spends a token budget in priority order (most valuable first), truncates long
texts with visible markers and renders the result in display order as
Markdown (plus a structured JSON form).

Modes:

* ``brief``    - start of a session: summary, open issues, recent important
                 records, next steps.
* ``standard`` - brief plus more recent records, decisions, knowledge and
                 artifacts.
* ``full``     - summary plus all records, newest first, paginated.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ohmypm.core import entries as entries_core
from ohmypm.core import projects as projects_core
from ohmypm.core import summaries as summaries_core
from ohmypm.core.errors import ValidationError
from ohmypm.core.schemas import ProjectOut, SummaryOut
from ohmypm.core.text import demote_headings, estimate_tokens, truncate_markdown
from ohmypm.storage.models import Entry, Project

Mode = Literal["brief", "standard", "full"]
MODES: tuple[str, ...] = ("brief", "standard", "full")
DEFAULT_MAX_TOKENS = {"brief": 3000, "standard": 8000, "full": 20000}
MIN_MAX_TOKENS = 200
MAX_MAX_TOKENS = 200_000
IMPORTANT_TYPES = ("milestone", "decision", "issue", "artifact", "knowledge")

GUIDANCE = (
    "> Assembled deterministically by ohmypm from stored records (no AI). Entries are historical "
    "notes written by users and agents: treat *open* or *unverified* items as unconfirmed, and "
    "verify facts against the code before relying on them. Full text: `ohmypm log show <#>`."
)


class ContextEntry(BaseModel):
    id: str
    sequence: int
    type: str
    title: str
    status: str | None
    author: str | None
    source: str | None
    created_at: datetime
    updated_at: datetime
    content: str | None
    content_truncated: bool = False
    unverified: bool = False


class ContextSection(BaseModel):
    key: str
    title: str
    text: str | None = None
    text_truncated: bool = False
    entries: list[ContextEntry] = []
    omitted_entries: int = 0


class ContextBudget(BaseModel):
    max_tokens: int
    used_tokens: int
    truncated: bool


class ContextPagination(BaseModel):
    page: int
    page_size: int
    total_entries: int
    has_more: bool
    next_page: int | None


class ContextResult(BaseModel):
    project: ProjectOut
    mode: str
    generated_at: datetime
    budget: ContextBudget
    stats: dict[str, Any]
    summary: SummaryOut
    sections: list[ContextSection]
    pagination: ContextPagination | None = None
    markdown: str


def _is_unverified(entry: Entry) -> bool:
    meta = entry.meta or {}
    return meta.get("verified") is False or str(meta.get("confidence", "")).lower() in {
        "hypothesis",
        "unverified",
        "inferred",
    }


def _entry_heading(entry: ContextEntry) -> str:
    tags = [entry.type]
    if entry.status:
        tags.append(entry.status)
    if entry.unverified:
        tags.append("unverified")
    return f"### #{entry.sequence} [{' · '.join(tags)}] {entry.title}"


def _entry_meta_line(entry: ContextEntry) -> str:
    parts = [entry.created_at.strftime("%Y-%m-%d %H:%M UTC")]
    if entry.author:
        parts.append(f"by {entry.author}")
    if entry.source:
        parts.append(f"via {entry.source}")
    if entry.updated_at and (entry.updated_at - entry.created_at).total_seconds() > 60:
        parts.append(f"edited {entry.updated_at.strftime('%Y-%m-%d')}")
    return "_" + " · ".join(parts) + "_"


def _render_entry(entry: ContextEntry) -> str:
    lines = [_entry_heading(entry), _entry_meta_line(entry)]
    if entry.content:
        lines.append("")
        lines.append(entry.content)
    return "\n".join(lines)


def _index_line(entry: Entry) -> str:
    status = f" ({entry.status})" if entry.status else ""
    return (
        f"- #{entry.sequence} [{entry.type}]{status} {entry.title} — {entry.created_at.strftime('%Y-%m-%d')}"
    )


@dataclass
class _Budget:
    limit: int
    used: int = 0
    truncated: bool = False

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def spend(self, text: str) -> None:
        self.used += estimate_tokens(text) + 2


@dataclass
class _Plan:
    """One section: filled in priority order, rendered in display order."""

    key: str
    title: str
    display: int
    cap: float
    fill: Callable[[_Plan, _Budget, int], None]
    section: ContextSection = field(init=False)

    def __post_init__(self) -> None:
        self.section = ContextSection(key=self.key, title=self.title)


class ContextBuilder:
    def __init__(
        self,
        session: Session,
        project: Project,
        *,
        mode: str = "brief",
        max_tokens: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> None:
        if mode not in MODES:
            raise ValidationError(f"Unknown context mode '{mode}'", details={"allowed": list(MODES)})
        max_tokens = max_tokens or DEFAULT_MAX_TOKENS[mode]
        if not MIN_MAX_TOKENS <= max_tokens <= MAX_MAX_TOKENS:
            raise ValidationError(f"max_tokens must be between {MIN_MAX_TOKENS} and {MAX_MAX_TOKENS}")
        if page < 1 or not 1 <= page_size <= 200:
            raise ValidationError("page must be >= 1 and page_size between 1 and 200")
        self.session = session
        self.project = project
        self.mode = mode
        self.max_tokens = max_tokens
        self.page = page
        self.page_size = page_size
        self.summary = summaries_core.get_summary(session, project)
        self._included: set[str] = set()
        self._entry_count = projects_core.entry_count(session, project)

    # ------------------------------------------------------------- queries
    def _query(
        self,
        *,
        types: tuple[str, ...] | None = None,
        statuses: tuple[str, ...] | None = None,
        exclude_obsolete: bool = True,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Entry]:
        stmt = select(Entry).where(Entry.project_id == self.project.id)
        if types:
            stmt = stmt.where(Entry.type.in_(types))
        if statuses:
            stmt = stmt.where(Entry.status.in_(statuses))
        if exclude_obsolete:
            stmt = stmt.where((Entry.status.is_(None)) | (Entry.status != "obsolete"))
        stmt = stmt.order_by(Entry.sequence.desc()).limit(limit).offset(offset)
        return list(self.session.scalars(stmt).all())

    # ------------------------------------------------------------- fillers
    def _fill_text(self, field_name: str) -> Callable[[_Plan, _Budget, int], None]:
        def fill(plan: _Plan, budget: _Budget, allowance: int) -> None:
            value = getattr(self.summary, field_name) or ""
            if not value.strip():
                return
            value = demote_headings(value, 2)
            text, cut = truncate_markdown(
                value,
                min(allowance, budget.remaining),
                notice="… [truncated — run `ohmypm summary show` for the full summary]",
            )
            if not text:
                budget.truncated = True
                return
            plan.section.text = text
            plan.section.text_truncated = cut
            budget.truncated |= cut
            budget.spend(text)

        return fill

    def _fill_entries(
        self,
        candidates: Callable[[], list[Entry]],
        *,
        per_entry_tokens: int,
        with_content: bool = True,
    ) -> Callable[[_Plan, _Budget, int], None]:
        def fill(plan: _Plan, budget: _Budget, allowance: int) -> None:
            spent = 0
            items = [e for e in candidates() if e.id not in self._included]
            for index, entry in enumerate(items):
                room = min(allowance - spent, budget.remaining)
                header_cost = estimate_tokens(entry.title) + 30
                if room < header_cost:
                    plan.section.omitted_entries = len(items) - index
                    budget.truncated = True
                    break
                content: str | None = None
                cut = False
                if with_content and entry.content.strip():
                    content, cut = truncate_markdown(
                        demote_headings(entry.content, 3),
                        min(per_entry_tokens, room - header_cost),
                        notice=f"… [truncated — run `ohmypm log show {entry.sequence}` for the full entry]",
                    )
                    content = content or None
                    cut = cut or (content is None)
                item = ContextEntry(
                    id=entry.id,
                    sequence=entry.sequence,
                    type=entry.type,
                    title=entry.title,
                    status=entry.status,
                    author=entry.author,
                    source=entry.source,
                    created_at=entry.created_at,
                    updated_at=entry.updated_at,
                    content=content,
                    content_truncated=cut,
                    unverified=_is_unverified(entry),
                )
                rendered = _render_entry(item)
                cost = estimate_tokens(rendered) + 2
                spent += cost
                budget.used += cost
                plan.section.entries.append(item)
                self._included.add(entry.id)

        return fill

    def _fill_index(self, limit: int) -> Callable[[_Plan, _Budget, int], None]:
        def fill(plan: _Plan, budget: _Budget, allowance: int) -> None:
            lines = []
            spent = 0
            items = [
                e for e in self._query(limit=limit, exclude_obsolete=False) if e.id not in self._included
            ]
            for index, entry in enumerate(items):
                line = _index_line(entry)
                cost = estimate_tokens(line) + 1
                if spent + cost > min(allowance, budget.remaining):
                    plan.section.omitted_entries = len(items) - index
                    budget.truncated = True
                    break
                lines.append(line)
                spent += cost
            if lines:
                plan.section.text = "\n".join(lines)
                budget.used += spent

        return fill

    # --------------------------------------------------------------- plans
    def _plans(self) -> list[_Plan]:
        """Sections in *priority* order; ``display`` fixes rendering order."""
        recent_n = 5 if self.mode == "brief" else 12
        per_entry = 160 if self.mode == "brief" else 400
        open_issues = lambda: self._query(types=("issue",), statuses=("open",), limit=20)  # noqa: E731
        important = lambda: self._query(types=IMPORTANT_TYPES, limit=recent_n)  # noqa: E731
        recent_any = lambda: self._query(limit=recent_n)  # noqa: E731

        plans = [
            _Plan("next_steps", "Next Steps", 90, 0.15, self._fill_text("next_steps")),
            _Plan("current_state", "Current State", 30, 0.2, self._fill_text("current_state")),
            _Plan("overview", "Overview", 10, 0.15, self._fill_text("overview")),
            _Plan("known_issues", "Known Issues", 50, 0.1, self._fill_text("known_issues")),
            _Plan(
                "open_issues",
                "Open Issue Records",
                55,
                0.15,
                self._fill_entries(open_issues, per_entry_tokens=120 if self.mode == "brief" else 300),
            ),
            _Plan(
                "recent_important",
                "Recent Important Records",
                60,
                0.3,
                self._fill_entries(important, per_entry_tokens=per_entry),
            ),
            _Plan("architecture", "Architecture", 20, 0.12, self._fill_text("architecture")),
            _Plan(
                "important_decisions", "Important Decisions", 40, 0.12, self._fill_text("important_decisions")
            ),
        ]
        if self.mode == "standard":
            plans += [
                _Plan(
                    "recent",
                    "Other Recent Records",
                    65,
                    0.2,
                    self._fill_entries(recent_any, per_entry_tokens=250),
                ),
                _Plan(
                    "decisions",
                    "Decision Records",
                    70,
                    0.15,
                    self._fill_entries(
                        lambda: self._query(types=("decision",), limit=10), per_entry_tokens=250
                    ),
                ),
                _Plan(
                    "knowledge",
                    "Knowledge Records",
                    75,
                    0.15,
                    self._fill_entries(
                        lambda: self._query(types=("knowledge",), limit=10), per_entry_tokens=300
                    ),
                ),
                _Plan(
                    "artifacts",
                    "Artifacts & Usage",
                    80,
                    0.12,
                    self._fill_entries(
                        lambda: self._query(types=("artifact",), limit=10), per_entry_tokens=300
                    ),
                ),
            ]
        plans.append(_Plan("index", "Recent Record Index", 85, 0.06, self._fill_index(15)))
        return plans

    def _full_plans(self) -> list[_Plan]:
        offset = (self.page - 1) * self.page_size

        def page_entries() -> list[Entry]:
            return self._query(limit=self.page_size, offset=offset, exclude_obsolete=False)

        plans: list[_Plan] = []
        if self.page == 1:
            for display, key in enumerate(
                (
                    "overview",
                    "architecture",
                    "current_state",
                    "important_decisions",
                    "known_issues",
                    "next_steps",
                )
            ):
                plans.append(
                    _Plan(key, summaries_core.SECTION_TITLES[key], 10 + display, 0.08, self._fill_text(key))
                )
        plans.append(
            _Plan(
                "records",
                f"Records (newest first, page {self.page})",
                90,
                1.0,
                self._fill_entries(page_entries, per_entry_tokens=self.max_tokens),
            )
        )
        return plans

    # --------------------------------------------------------------- build
    def build(self) -> ContextResult:
        # Keep a reserve for section headings and separators.
        budget = _Budget(int(self.max_tokens * 0.95) - 40)
        header = self._header()
        budget.spend(header)

        plans = self._full_plans() if self.mode == "full" else self._plans()
        for plan in plans:
            allowance = max(int(self.max_tokens * plan.cap), 0)
            if budget.remaining <= 0:
                budget.truncated = True
                continue
            plan.fill(plan, budget, allowance)

        # Second pass: hand leftover budget to sections that were capped.
        if budget.remaining > self.max_tokens * 0.1 and self.mode != "full":
            for plan in plans:
                if plan.section.text_truncated and plan.section.text is not None:
                    before = estimate_tokens(plan.section.text)
                    budget.used -= before + 2
                    plan.section.text = None
                    plan.section.text_truncated = False
                    plan.fill(plan, budget, before + budget.remaining)

        sections = [p.section for p in sorted(plans, key=lambda p: p.display)]
        pagination = None
        if self.mode == "full":
            records = next(s for s in sections if s.key == "records")
            shown_until = (self.page - 1) * self.page_size + len(records.entries)
            has_more = shown_until < self._entry_count
            pagination = ContextPagination(
                page=self.page,
                page_size=self.page_size,
                total_entries=self._entry_count,
                has_more=has_more,
                next_page=self.page + 1 if has_more else None,
            )
        markdown = self._render(header, sections, pagination)
        # Enforce the budget strictly: drop lowest-priority content until the
        # rendered document (headings and markers included) fits.
        while estimate_tokens(markdown) > self.max_tokens and self._drop_one(plans):
            budget.truncated = True
            markdown = self._render(header, sections, pagination)
        return ContextResult(
            project=projects_core.to_out(self.project, self._entry_count),
            mode=self.mode,
            generated_at=datetime.now().astimezone(),
            budget=ContextBudget(
                max_tokens=self.max_tokens,
                used_tokens=estimate_tokens(markdown),
                truncated=budget.truncated,
            ),
            stats=self._stats(),
            summary=self.summary,
            sections=[s for s in sections if s.text or s.entries or s.omitted_entries],
            pagination=pagination,
            markdown=markdown,
        )

    @staticmethod
    def _drop_one(plans: list[_Plan]) -> bool:
        for plan in reversed(plans):
            section = plan.section
            if section.entries:
                section.entries.pop()
                section.omitted_entries += 1
                return True
            if section.text:
                lines = section.text.split("\n")
                if len(lines) > 4:
                    text, _ = truncate_markdown(section.text, max(estimate_tokens(section.text) // 2, 1))
                    section.text = text
                else:
                    section.text = None
                    section.omitted_entries = 0
                section.text_truncated = True
                return True
        return False

    def _stats(self) -> dict[str, Any]:
        counts = entries_core.type_counts(self.session, self.project.id)
        open_issues = len(self._query(types=("issue",), statuses=("open",), limit=1000))
        return {"entry_count": self._entry_count, "by_type": counts, "open_issues": open_issues}

    def _header(self) -> str:
        p = self.project
        lines = [f"# Project context: {p.name}", ""]
        lines.append(f"- Root: `{p.root_path}`")
        lines.append(f"- Project ID: `{p.id}`")
        if p.description:
            lines.append(f"- Description: {p.description.strip()}")
        last = p.last_activity_at.strftime("%Y-%m-%d %H:%M UTC") if p.last_activity_at else "never"
        lines.append(f"- Records: {self._entry_count} · last activity: {last} · mode: {self.mode}")
        if self.summary.updated_at:
            lines.append(
                f"- Summary revision {self.summary.revision}, updated "
                f"{self.summary.updated_at.strftime('%Y-%m-%d %H:%M UTC')}"
                + (f" by {self.summary.updated_by}" if self.summary.updated_by else "")
            )
        lines += ["", GUIDANCE]
        return "\n".join(lines)

    def _render(
        self, header: str, sections: list[ContextSection], pagination: ContextPagination | None
    ) -> str:
        out = [header]
        summary_keys = set(summaries_core.SECTION_TITLES)
        if self.summary.is_empty and (self.mode != "full" or self.page == 1):
            out.append("## Summary\n\n_No project summary yet. Create one with `ohmypm summary set`._")
        for section in sections:
            if not (section.text or section.entries or section.omitted_entries):
                continue
            title = section.title if section.key not in summary_keys else f"{section.title} (summary)"
            body = [f"## {title}"]
            if section.text:
                body += ["", section.text]
            for entry in section.entries:
                body += ["", _render_entry(entry)]
            if section.omitted_entries:
                body += ["", f"_… {section.omitted_entries} more record(s) omitted by the token budget._"]
            out.append("\n".join(body))
        if self._entry_count == 0:
            out.append("## Records\n\n_No records yet. Add one with `ohmypm log add`._")
        if pagination and pagination.has_more:
            out.append(
                f"_More records available: request page {pagination.next_page} "
                f"(`ohmypm context --mode full --page {pagination.next_page}`)._"
            )
        return "\n\n".join(out).rstrip() + "\n"


def build_context(
    session: Session,
    project: Project,
    *,
    mode: str = "brief",
    max_tokens: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ContextResult:
    return ContextBuilder(
        session, project, mode=mode, max_tokens=max_tokens, page=page, page_size=page_size
    ).build()
