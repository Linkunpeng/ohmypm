"""ContextBuilder: deterministic, budgeted resume context for agents.

Sections are assembled in priority order. Each section renders to markdown; sections are
added until the token budget is spent, the last one truncated to fit. No LLM is involved, so
the same database state always produces the same context.

Modes:
- brief:    task goal/state, project summary, latest checkpoint, blockers, next action
- standard: + decisions, relevant knowledge, key files, recent runs, artifacts, earlier checkpoints
- full:     + full checkpoint history, task timeline, subtasks, more knowledge
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, or_, select

from ohmypm.models import (
    AgentRun,
    Artifact,
    Checkpoint,
    Decision,
    Project,
    ProjectKnowledge,
    Task,
    TaskDependency,
    TaskEvent,
    Workspace,
)
from ohmypm.schemas import ContextOut
from ohmypm.services.common import Ctx, dedupe
from ohmypm.services.tasks import get_task
from ohmypm_common.enums import ContextMode, DecisionStatus, TaskStatus

_CJK = re.compile(r"[\u3000-\u9fff\uac00-\ud7af\uf900-\ufaff]")


def estimate_tokens(text: str) -> int:
    """Cheap tokenizer-free estimate: CJK ≈ 1 token/char, other text ≈ 4 chars/token."""
    cjk = len(_CJK.findall(text))
    return cjk + (len(text) - cjk + 3) // 4


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _bullets(items: Sequence[str], limit: int = 30, clip: int = 400) -> str:
    shown = [f"- {_clip(i, clip)}" for i in items[:limit]]
    if len(items) > limit:
        shown.append(f"- … {len(items) - limit} more")
    return "\n".join(shown)


@dataclass
class Section:
    name: str
    data: Any
    markdown: str
    essential: bool = False


@dataclass
class _Budget:
    max_tokens: int
    used: int = 0
    truncated: bool = False
    included: list[Section] = field(default_factory=list)

    def add(self, section: Section) -> None:
        if not section.markdown.strip():
            return
        cost = estimate_tokens(section.markdown)
        remaining = self.max_tokens - self.used
        if cost <= remaining:
            self.included.append(section)
            self.used += cost
            return
        self.truncated = True
        if remaining < 60 and not section.essential:
            return
        # Truncate the markdown to the remaining budget (keep data; flag truncation).
        ratio = max(remaining, 60) / cost
        cut = section.markdown[: max(200, int(len(section.markdown) * ratio) - 40)]
        clipped = Section(
            section.name, section.data, cut.rstrip() + "\n\n_[section truncated to fit budget]_", section.essential
        )
        self.included.append(clipped)
        self.used += estimate_tokens(clipped.markdown)


def _checkpoint_dict(cp: Checkpoint, *, compact: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(cp.id),
        "created_at": cp.created_at.isoformat(),
        "created_by": cp.created_by,
        "auto_generated": cp.auto_generated,
        "summary": cp.summary,
    }
    if compact:
        return data
    data.update(
        completed=cp.completed,
        remaining=cp.remaining,
        current_issue=cp.current_issue,
        attempts=cp.attempts,
        findings=cp.findings,
        relevant_files=cp.relevant_files,
        next_steps=cp.next_steps,
        verification=cp.verification,
    )
    return data


def _render_checkpoint(cp: Checkpoint, heading: str) -> str:
    lines = [
        f"## {heading}",
        f"_{cp.created_at:%Y-%m-%d %H:%M} by {cp.created_by or 'unknown'}"
        f"{' (auto-generated)' if cp.auto_generated else ''}_",
        "",
        _clip(cp.summary, 3000),
    ]
    if cp.completed:
        lines += ["", "**Completed:**", _bullets(cp.completed)]
    if cp.remaining:
        lines += ["", "**Remaining:**", _bullets(cp.remaining)]
    issue = cp.current_issue or {}
    if any(issue.get(k) for k in ("description", "error", "root_cause")):
        lines += ["", "**Current issue:**"]
        for key in ("description", "error", "root_cause"):
            if issue.get(key):
                lines.append(f"- {key}: {_clip(str(issue[key]), 1500)}")
    if cp.attempts:
        lines += ["", "**Attempts (do not repeat failed ones blindly):**"]
        for a in cp.attempts[-10:]:
            conclusion = f" → {a.get('conclusion')}" if a.get("conclusion") else ""
            lines.append(
                f"- {_clip(str(a.get('action', '')), 300)}: {_clip(str(a.get('result', '')), 400)}{conclusion}"
            )
    if cp.findings:
        lines += ["", "**Findings:**"]
        for f in cp.findings[-15:]:
            lines.append(f"- [{f.get('kind', 'verified')}] {_clip(str(f.get('statement', '')), 400)}")
    if cp.next_steps:
        lines += ["", "**Next steps:**", _bullets(cp.next_steps, 15)]
    if cp.verification:
        lines += ["", "**Verification:**"]
        for v in cp.verification[-5:]:
            passed = v.get("passed")
            mark = " ✓" if passed is True else " ✗" if passed is False else ""
            lines.append(f"- `{_clip(str(v.get('command', '')), 300)}` → {_clip(str(v.get('result', '')), 300)}{mark}")
    if cp.relevant_files:
        lines += ["", "**Relevant files:** " + ", ".join(f"`{p}`" for p in cp.relevant_files[:30])]
    return "\n".join(lines)


async def build_context(
    ctx: Ctx,
    task_id: uuid.UUID,
    *,
    mode: ContextMode = ContextMode.BRIEF,
    max_tokens: int | None = None,
    checkpoint_id: uuid.UUID | None = None,
) -> ContextOut:
    budget = _Budget(max_tokens=max(200, min(max_tokens or ctx.settings.context_default_max_tokens, 50_000)))
    s = ctx.session
    task = await get_task(ctx, task_id)
    standard = mode in (ContextMode.STANDARD, ContextMode.FULL)
    full = mode is ContextMode.FULL

    project = await s.get(Project, task.project_id) if task.project_id else None
    workspace = await s.get(Workspace, task.workspace_id) if task.workspace_id else None

    checkpoints = (
        (
            await s.execute(
                select(Checkpoint)
                .where(Checkpoint.task_id == task.id)
                .order_by(Checkpoint.created_at.desc())
                .limit(50 if full else 6)
            )
        )
        .scalars()
        .all()
    )
    latest: Checkpoint | None = None
    if checkpoint_id is not None:
        latest = next((c for c in checkpoints if c.id == checkpoint_id), None) or await s.get(Checkpoint, checkpoint_id)
    elif checkpoints:
        # Prefer the newest agent-written checkpoint; auto ones only if nothing else exists.
        latest = next((c for c in checkpoints if not c.auto_generated), checkpoints[0])

    decisions = (
        (await s.execute(select(Decision).where(Decision.task_id == task.id).order_by(Decision.created_at.desc())))
        .scalars()
        .all()
    )
    pending = [d for d in decisions if d.status == DecisionStatus.PENDING]

    deps = (
        (
            await s.execute(
                select(Task)
                .join(TaskDependency, TaskDependency.depends_on_id == Task.id)
                .where(TaskDependency.task_id == task.id)
            )
        )
        .scalars()
        .all()
    )

    # ---- 1. task (essential)
    raw_limit = 6000 if full else 2500 if standard else 1500
    task_data = {
        "id": str(task.id),
        "key": f"T-{task.number}",
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "raw_request": task.raw_request,
        "description": task.description,
        "acceptance_criteria": task.acceptance_criteria,
        "completed_items": task.completed_items,
        "remaining_items": task.remaining_items,
        "next_action": task.next_action,
        "blockers": task.blockers,
        "acceptance_result": task.acceptance_result,
    }
    lines = [
        f"# Task T-{task.number}: {task.title}",
        f"Status: **{task.status}** · Priority: {task.priority} · Task ID: `{task.id}`",
        "",
        "## Original request (verbatim)",
        _clip(task.raw_request, raw_limit),
    ]
    if task.description and task.description.strip() != task.raw_request.strip():
        lines += ["", "## Structured description", _clip(task.description, raw_limit)]
    if task.acceptance_criteria:
        lines += ["", "## Acceptance criteria", _bullets(task.acceptance_criteria)]
    budget.add(Section("task", task_data, "\n".join(lines), essential=True))

    # ---- 2. current state (essential)
    state_lines = ["## Current state"]
    if task.completed_items:
        state_lines += ["**Done so far:**", _bullets(task.completed_items[-25:])]
    if task.remaining_items:
        state_lines += ["**Remaining:**", _bullets(task.remaining_items)]
    if task.blockers:
        state_lines += ["**Blockers:**", _bullets(task.blockers)]
    unmet = [d for d in deps if d.status != TaskStatus.COMPLETED]
    if unmet:
        state_lines += [
            "**Unfinished dependencies:**",
            _bullets([f"T-{d.number} {d.title} ({d.status})" for d in unmet]),
        ]
    if pending:
        state_lines += [
            "**Waiting for user decisions:**",
            _bullets([f"{d.question} (decision `{d.id}`)" for d in pending]),
        ]
    state_lines.append(f"**Next action:** {task.next_action or '(not recorded)'}")
    budget.add(
        Section(
            "state",
            {"unmet_dependencies": [str(d.id) for d in unmet], "pending_decisions": [str(d.id) for d in pending]},
            "\n".join(state_lines),
            essential=True,
        )
    )

    # ---- 3. project
    if project is not None or workspace is not None:
        p_lines = ["## Project"]
        p_data: dict[str, Any] = {}
        if project is not None:
            p_lines.append(f"**{project.name}** (`{project.id}`)")
            if project.description:
                p_lines.append(_clip(project.description, 1500 if standard else 600))
            p_data.update(id=str(project.id), name=project.name, description=project.description)
        else:
            p_lines.append("Anonymous workspace (no PROJECT_ID).")
        if workspace is not None:
            p_lines.append(f"Workspace: `{workspace.root_path}` on host `{workspace.host_id}`")
            p_data["workspace"] = {
                "id": str(workspace.id),
                "root_path": workspace.root_path,
                "host_id": workspace.host_id,
            }
        budget.add(Section("project", p_data, "\n".join(p_lines)))

    # ---- 4. latest checkpoint
    if latest is not None:
        heading = "Selected checkpoint" if checkpoint_id else "Latest checkpoint"
        budget.add(Section("latest_checkpoint", _checkpoint_dict(latest), _render_checkpoint(latest, heading)))

    # Lowest-priority sections, added after everything else.
    deferred: list[Section] = []

    if standard:
        resolved = [d for d in decisions if d.status == DecisionStatus.RESOLVED][: (30 if full else 8)]
        if resolved:
            d_lines = ["## Decisions made by the user"]
            for d in resolved:
                answer = d.selected_option or ""
                if d.response:
                    answer = f"{answer} — {d.response}" if answer else d.response
                d_lines.append(f"- Q: {_clip(d.question, 300)}\n  A: {_clip(answer, 600)}")
            budget.add(
                Section(
                    "decisions",
                    [
                        {
                            "id": str(d.id),
                            "question": d.question,
                            "selected_option": d.selected_option,
                            "response": d.response,
                        }
                        for d in resolved
                    ],
                    "\n".join(d_lines),
                )
            )

        knowledge = await _relevant_knowledge(ctx, task, limit=20 if full else 8)
        if knowledge:
            k_lines = ["## Project knowledge"]
            for k in knowledge:
                mark = "verified" if k.verified else "unverified"
                k_lines.append(f"### {k.title} ({k.category}, {mark})\n{_clip(k.content, 1500 if full else 700)}")
            budget.add(
                Section(
                    "knowledge",
                    [
                        {"id": str(k.id), "title": k.title, "category": k.category, "verified": k.verified}
                        for k in knowledge
                    ],
                    "\n\n".join(k_lines),
                )
            )

        files = dedupe([f for cp in checkpoints for f in cp.relevant_files])[:40]
        if files:
            budget.add(Section("key_files", files, "## Key files\n" + "\n".join(f"- `{f}`" for f in files)))

        runs = (
            (
                await s.execute(
                    select(AgentRun)
                    .where(AgentRun.task_id == task.id)
                    .order_by(AgentRun.created_at.desc())
                    .limit(15 if full else 5)
                )
            )
            .scalars()
            .all()
        )
        if runs:
            r_lines = ["## Recent runs"]
            for r in runs:
                detail = r.error or r.result_summary or ""
                r_lines.append(
                    f"- {r.created_at:%Y-%m-%d %H:%M} {r.agent_type} → **{r.status}**"
                    + (f": {_clip(detail, 300)}" if detail else "")
                )
            budget.add(
                Section(
                    "runs",
                    [
                        {
                            "id": str(r.id),
                            "agent_type": r.agent_type,
                            "status": r.status,
                            "error": r.error,
                            "result_summary": _clip(r.result_summary or "", 500),
                        }
                        for r in runs
                    ],
                    "\n".join(r_lines),
                )
            )

        artifacts = (
            (
                await s.execute(
                    select(Artifact).where(Artifact.task_id == task.id).order_by(Artifact.updated_at.desc()).limit(20)
                )
            )
            .scalars()
            .all()
        )
        if artifacts:
            a_lines = ["## Artifacts"]
            for a in artifacts:
                usage = (a.usage or {}).get("command")
                a_lines.append(
                    f"- **{a.name}** ({a.type}) at `{a.storage_uri}`" + (f" — run: `{usage}`" if usage else "")
                )
            budget.add(
                Section(
                    "artifacts",
                    [
                        {"id": str(a.id), "name": a.name, "type": a.type, "storage_uri": a.storage_uri}
                        for a in artifacts
                    ],
                    "\n".join(a_lines),
                )
            )

        earlier = [c for c in checkpoints if latest is None or c.id != latest.id]
        if earlier:
            if full:
                for cp in earlier:
                    deferred.append(
                        Section(
                            f"checkpoint:{cp.id}", _checkpoint_dict(cp), _render_checkpoint(cp, "Earlier checkpoint")
                        )
                    )
            else:
                e_lines = ["## Earlier checkpoints"]
                for cp in earlier[:3]:
                    e_lines.append(f"- {cp.created_at:%Y-%m-%d %H:%M}: {_clip(cp.summary, 300)}")
                budget.add(
                    Section(
                        "earlier_checkpoints",
                        [_checkpoint_dict(c, compact=True) for c in earlier[:3]],
                        "\n".join(e_lines),
                    )
                )

    if full:
        subtasks = (
            (await s.execute(select(Task).where(Task.parent_task_id == task.id).order_by(Task.number))).scalars().all()
        )
        if subtasks:
            budget.add(
                Section(
                    "subtasks",
                    [{"id": str(t.id), "key": f"T-{t.number}", "title": t.title, "status": t.status} for t in subtasks],
                    "## Subtasks\n" + _bullets([f"T-{t.number} {t.title} ({t.status})" for t in subtasks]),
                )
            )
        events = (
            (
                await s.execute(
                    select(TaskEvent).where(TaskEvent.task_id == task.id).order_by(TaskEvent.id.desc()).limit(60)
                )
            )
            .scalars()
            .all()
        )
        if events:
            ev_lines = ["## Timeline (most recent first)"]
            for ev in events:
                ev_lines.append(
                    f"- {ev.created_at:%Y-%m-%d %H:%M} {ev.event_type} by {ev.actor or '?'}" + _event_hint(ev.payload)
                )
            deferred.append(Section("timeline", None, "\n".join(ev_lines)))

    for section in deferred:
        budget.add(section)

    markdown = "\n\n".join(sec.markdown for sec in budget.included)
    return ContextOut(
        task_id=task.id,
        mode=mode,
        max_tokens=budget.max_tokens,
        estimated_tokens=estimate_tokens(markdown),
        truncated=budget.truncated,
        sections=[sec.name for sec in budget.included],
        data={sec.name: sec.data for sec in budget.included if sec.data is not None},
        markdown=markdown,
    )


def _event_hint(payload: dict[str, Any]) -> str:
    for key in ("to", "summary", "question", "status", "title"):
        if payload.get(key):
            return f": {_clip(str(payload[key]), 120)}"
    return ""


async def _relevant_knowledge(ctx: Ctx, task: Task, *, limit: int) -> Sequence[ProjectKnowledge]:
    stmt = select(ProjectKnowledge).where(ProjectKnowledge.superseded_by.is_(None))
    if task.project_id is not None:
        stmt = stmt.where(or_(ProjectKnowledge.project_id == task.project_id, ProjectKnowledge.project_id.is_(None)))
    else:
        stmt = stmt.where(ProjectKnowledge.project_id.is_(None))
    words = [w for w in re.findall(r"\w+", f"{task.title} {task.next_action}") if len(w) > 2][:12]
    if words:
        tsq = func.to_tsquery("simple", " | ".join(f"'{w}'" for w in words))
        rank = func.ts_rank(ProjectKnowledge.search_vector, tsq)
        stmt = stmt.order_by(rank.desc(), ProjectKnowledge.verified.desc(), ProjectKnowledge.updated_at.desc())
    else:
        stmt = stmt.order_by(ProjectKnowledge.verified.desc(), ProjectKnowledge.updated_at.desc())
    return (await ctx.session.execute(stmt.limit(limit))).scalars().all()
