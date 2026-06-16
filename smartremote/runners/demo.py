"""Minimal runner used by the self-test and as a template for new runners."""
from __future__ import annotations

from . import Outcome, RunContext, Runner


class DemoRunner(Runner):
    name = "demo"

    def run(self, ctx: RunContext) -> Outcome:
        answer = ctx.ask("demo-q", "Demo question: reply with anything to continue.")
        return Outcome(summary=f"Demo finished with answer={answer!r}")
