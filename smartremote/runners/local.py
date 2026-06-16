"""Local-agent runner — STUB.

The offline executor that runs on the 4090 (e.g. a small quantized model via
Ollama/vLLM, or Hermes Agent itself). It executes an already-written
artifacts/plan.md and must not require internet. Keep its VRAM footprint small
(7-8B ~ 6 GB) so it can coexist with — or yield to — GPU training.
"""
from __future__ import annotations

from . import Outcome, RunContext, Runner


class LocalRunner(Runner):
    name = "local"

    def run(self, ctx: RunContext) -> Outcome:
        plan = ctx.job_dir / "artifacts" / "plan.md"
        if not plan.exists():
            raise RuntimeError(
                "No artifacts/plan.md to execute. A cloud planner must produce a "
                "plan first (set agent: cloud, or add a depends_on planning job)."
            )
        # --- replace with a real local-model execution loop ---------------
        return Outcome(
            summary=f"Executed plan ({plan.stat().st_size} bytes) on local model (stub).",
        )
        # ------------------------------------------------------------------
