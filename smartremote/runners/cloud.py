"""Cloud-agent runner — STUB.

In production this hands the job body to a frontier agent with internet access
(Claude Code or Codex), which drafts a plan, can ask the human via ctx.ask(), and
emits artifacts/plan.md for the local executor. The stub below performs the real
control flow (draft -> human approval -> finalize) so the park/resume machinery is
exercised end to end without an API key. Replace the marked section with a real
agent invocation (e.g. shell out to `claude -p` or the Codex CLI in job_dir).
"""
from __future__ import annotations

import shutil

from . import Outcome, RunContext, Runner


class CloudRunner(Runner):
    name = "cloud"

    def run(self, ctx: RunContext) -> Outcome:
        planner = ctx.roles.get("planner") or {}
        print(f"[cloud] planning with {planner.get('provider', '?')}:{planner.get('model', '?')}", flush=True)
        ctx.set_step("plan")
        draft = ctx.job_dir / "workspace" / "plan.draft.md"
        if not draft.exists():  # idempotent: survives resume replay
            # --- replace with a real planner call -------------------------
            draft.write_text(
                f"# Draft plan for {ctx.job.id}\n\n{ctx.job.body.strip()}\n\n"
                "1. (planner stub) decompose into steps\n2. ...\n",
                encoding="utf-8",
            )
            # --------------------------------------------------------------

        ctx.set_step("approve")
        decision = ctx.ask(
            "approve-plan",
            f"Approve the drafted plan for '{ctx.job.title}'? "
            "Reply: approve / revise / reject.",
            choices=["approve", "revise", "reject"],
        ).lower()

        if decision.startswith("approve"):
            final = ctx.job_dir / "artifacts" / "plan.md"
            shutil.copy2(draft, final)
            return Outcome(
                summary="Plan approved and finalized.",
                artifacts=[str(final.relative_to(ctx.job_dir))],
            )
        if decision.startswith("reject"):
            raise RuntimeError("Plan rejected by human; aborting job.")
        ctx.checkpoint["revise_count"] = ctx.checkpoint.get("revise_count", 0) + 1
        raise RuntimeError("Revision requested — wire this to the planner loop.")
