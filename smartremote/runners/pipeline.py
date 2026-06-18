"""PlanExecuteRunner: the wired plan -> (approve) -> execute -> guard -> escalate flow.

Roles (config-driven; see smartremote.config and `smartremote models`):
  planner    (remote) writes artifacts/plan.md from the job body
  executor   (local)  applies the plan        -> artifacts/result.md
  guard      (remote) checks result vs plan   -> JSON verdict {ok, issues, summary}
  escalation (remote) takes over if the guard fails -> artifacts/result.escalated.md

Used for build/train/pipeline jobs; research jobs use CloudRunner. Steps before the
optional human-approval checkpoint are idempotent (guarded by plan.md existing), so
the runner replays cleanly on resume.
"""
from __future__ import annotations

from ..providers import parse_verdict, provider_for_role
from . import Outcome, RunContext, Runner

PLAN_SYSTEM = (
    "You are the planner. Produce a concise, numbered, step-by-step plan in Markdown that "
    "another agent can execute. Be specific and verifiable. Output only the plan."
)
EXEC_SYSTEM = (
    "You are the executor. Carry out the PLAN for the TASK and report exactly what you did "
    "and the resulting artifacts. Be concrete."
)
GUARD_SYSTEM = (
    "You are the guard. Decide whether RESULT faithfully satisfies PLAN. Respond with ONLY a "
    'JSON object: {"ok": true|false, "issues": [..], "summary": ".."}.'
)
ESC_SYSTEM = (
    "You are the escalation agent (a stronger remote model). The local model's RESULT failed "
    "the guard. Either redo the task correctly to satisfy the PLAN, or — if the local model is "
    "fundamentally too weak — recommend a better local model (an Ollama tag) and say why."
)


class PlanExecuteRunner(Runner):
    name = "plan-execute"

    def run(self, ctx: RunContext) -> Outcome:
        artifacts = ctx.job_dir / "artifacts"
        artifacts.mkdir(exist_ok=True)
        workspace = ctx.job_dir / "workspace"
        plan_path = artifacts / "plan.md"

        # 1. PLAN (remote) — skip if a plan already exists (offline / pre-supplied).
        if not plan_path.exists():
            ctx.set_step("plan")
            planner = provider_for_role(ctx.cfg, "planner")
            plan_path.write_text(
                planner.complete(ctx.job.body, system=PLAN_SYSTEM, workspace=workspace),
                encoding="utf-8")
        plan = plan_path.read_text(encoding="utf-8")

        # 2. APPROVE (optional human checkpoint) — parks the job until answered.
        if ctx.job.needs_human:
            decision = ctx.ask("approve-plan", f"Approve this plan?\n\n{plan[:1500]}",
                               choices=["approve", "revise", "reject"]).lower()
            if decision.startswith("reject"):
                raise RuntimeError("plan rejected by human")

        # 3. EXECUTE (local).
        ctx.set_step("execute")
        executor = provider_for_role(ctx.cfg, "executor")
        result = executor.complete(f"PLAN:\n{plan}\n\nTASK:\n{ctx.job.body}",
                                   system=EXEC_SYSTEM, workspace=workspace)
        (artifacts / "result.md").write_text(result, encoding="utf-8")

        # 4. GUARD (remote) — does the result satisfy the plan?
        ctx.set_step("guard")
        guard = provider_for_role(ctx.cfg, "guard")
        verdict = parse_verdict(
            guard.complete(f"PLAN:\n{plan}\n\nRESULT:\n{result}", system=GUARD_SYSTEM, workspace=workspace))

        # 5. ESCALATE (remote takes over) if the guard failed — once.
        escalated = False
        if not verdict["ok"] and not ctx.checkpoint.get("escalated"):
            ctx.set_step("escalate")
            ctx.checkpoint["escalated"] = True
            esc = provider_for_role(ctx.cfg, "escalation")
            fixed = esc.complete(
                f"PLAN:\n{plan}\n\nLOCAL RESULT:\n{result}\n\nGUARD ISSUES:\n{verdict['issues']}",
                system=ESC_SYSTEM, workspace=workspace)
            (artifacts / "result.escalated.md").write_text(fixed, encoding="utf-8")
            escalated = True

        arts = ["artifacts/plan.md", "artifacts/result.md"]
        if escalated:
            arts.append("artifacts/result.escalated.md")
        status = "ok" if verdict["ok"] else f"flagged ({verdict['summary']})"
        summary = f"plan->execute->guard [{status}]" + (" -> escalated to remote" if escalated else "")
        return Outcome(summary=summary, artifacts=arts)
