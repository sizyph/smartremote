"""CloudRunner: research / remote-only jobs.

The remote agent (the `planner` role — Claude Code / Codex) produces the
deliverable directly. Routed for `type: research`.
"""
from __future__ import annotations

from ..providers import provider_for_role
from . import Outcome, RunContext, Runner

RESEARCH_SYSTEM = (
    "You are a research agent with web access. Produce a thorough, well-structured, "
    "cited Markdown report that answers the request. Output only the report."
)


class CloudRunner(Runner):
    name = "cloud"

    def run(self, ctx: RunContext) -> Outcome:
        (ctx.job_dir / "artifacts").mkdir(exist_ok=True)
        agent = provider_for_role(ctx.cfg, "planner")
        report = agent.complete(ctx.job.body, system=RESEARCH_SYSTEM, workspace=ctx.job_dir / "workspace")
        (ctx.job_dir / "artifacts" / "report.md").write_text(report, encoding="utf-8")
        return Outcome(summary="research report generated", artifacts=["artifacts/report.md"])
