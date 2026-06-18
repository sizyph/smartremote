"""ScoutRunner: the model-scout job.

Benchmarks the current executor (champion) against challenger models, then asks for
approval (via Hermes, by parking) before promoting the winner to the executor role.
Routed for jobs with `runner: scout`; runs as `gpu: required` (it loads models).

Challengers come from a `## Challengers` list in the job body (one Ollama tag per
`- ` line), else the recommended 24 GB catalog. Find fresh candidates with
`smartremote models scout` (a web-research pass) and paste them into the job.
"""
from __future__ import annotations

from .. import models as catalog
from .. import scout as scoutmod
from ..config import update_local
from . import Outcome, RunContext, Runner


class ScoutRunner(Runner):
    name = "scout"

    def run(self, ctx: RunContext) -> Outcome:
        artifacts = ctx.job_dir / "artifacts"
        artifacts.mkdir(exist_ok=True)
        models_cfg = ctx.cfg["models"]
        champion = (models_cfg["roles"].get("executor") or {}).get("model", "")
        base_url = models_cfg["local"]["base_url"]

        challengers = _parse_challengers(ctx.job.body) or [r.tag for r in catalog.RECOMMENDED]
        tags = list(dict.fromkeys(([champion] if champion else []) + challengers))

        results = [scoutmod.benchmark_model(t, base_url) for t in tags]
        report = scoutmod.report_table(results, champion)
        (artifacts / "scout-report.md").write_text("# Model scout\n\n" + report + "\n", encoding="utf-8")

        winner = scoutmod.choose_winner(champion, results)
        if not winner:
            return Outcome(
                summary=f"champion '{champion or '(none)'}' retained — no challenger cleared the bar",
                artifacts=["artifacts/scout-report.md"])

        # Promotion is a real change: ask the human (parks; Hermes delivers the question).
        decision = ctx.ask(
            "promote-model",
            f"Promote the executor from '{champion or '(none)'}' to '{winner}'?\n\n{report}",
            choices=["approve", "keep"]).lower()
        if decision.startswith("approve"):
            update_local(ctx.job_dir.parent.parent,
                         {"models": {"roles": {"executor": {"provider": "local", "model": winner}}}})
            return Outcome(summary=f"promoted executor: '{champion or '(none)'}' -> '{winner}'",
                           artifacts=["artifacts/scout-report.md"])
        return Outcome(summary=f"kept '{champion}'; '{winner}' not promoted",
                       artifacts=["artifacts/scout-report.md"])


def _parse_challengers(body: str) -> list[str]:
    tags, in_section = [], False
    for line in body.splitlines():
        s = line.strip()
        if s.lower().startswith("## challenger"):
            in_section = True
            continue
        if in_section:
            if s.startswith("#"):
                break
            if s.startswith("- "):
                tags.append(s[2:].strip())
    return tags
