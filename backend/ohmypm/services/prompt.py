"""Prompt sent to an agent CLI for a run: resume context + instructions + reporting protocol."""

from __future__ import annotations

from ohmypm.models import AgentRun, Task
from ohmypm.services.common import Ctx
from ohmypm.services.context import build_context
from ohmypm_common.enums import ContextMode

PROTOCOL = """## How to report progress (ohmypm)
ohmypm is the persistent memory for this task. Another agent may continue after you, so leave a clear trail.
If the `ohmypm` MCP tools are available (pm_get_context, pm_checkpoint, pm_update_task, pm_manage_decision,
pm_register_artifact, pm_complete_task):
- Call `pm_checkpoint` after meaningful progress and before you stop: what is done, what remains, important
  failed attempts and their results, findings marked verified / inferred / hypothesis, relevant files,
  next steps and verification commands. Keep it concise; no step-by-step logs.
- If a high-impact choice needs the user, create a decision with `pm_manage_decision` (action="create") and
  stop instead of guessing.
- Register deliverables (binaries, scripts, reports, models…) with `pm_register_artifact`, including how to
  build, run and verify them.
- Call `pm_complete_task` only when every acceptance criterion is verified, with evidence for each.
If the tools are not available, end your final message with sections "Done", "Remaining" and "Next step".
Use task_id `{task_id}` with these tools. This run is `{run_id}`."""


async def build_run_prompt(ctx: Ctx, run: AgentRun, task: Task) -> str:
    try:
        mode = ContextMode(run.context_mode)
    except ValueError:
        mode = ContextMode.STANDARD
    budget = {ContextMode.BRIEF: 2500, ContextMode.STANDARD: 6000, ContextMode.FULL: 16000}[mode]
    context = await build_context(ctx, task.id, mode=mode, max_tokens=budget, checkpoint_id=run.from_checkpoint_id)
    instructions = run.instructions.strip() or (
        "Continue working on this task toward its acceptance criteria, starting from the next action above."
    )
    parts = [
        "You are an AI agent working on a task tracked by ohmypm. The context below was generated from the task's "
        "recorded history; treat it as the source of truth about prior work, but verify the workspace state.",
        context.markdown,
        "## Instructions for this run\n" + instructions,
        PROTOCOL.format(task_id=task.id, run_id=run.id),
    ]
    return "\n\n".join(parts)
