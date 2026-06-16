"""Runner interface + the ask()/park() human-in-the-loop mechanism.

A runner executes a job. When it needs a human decision it calls `ctx.ask()`. If
no answer exists yet, ask() persists the question + checkpoint and raises
`ParkSignal`, which run_job turns into exit code 42 ("parked"). The dispatcher then
releases the GPU, notifies the human, and re-launches the runner once an answer
arrives. On re-launch the same ask() call finds the answer file and returns it, so
runner code is written as straight-line replay that transparently skips answered
questions. Keep side effects before an ask() idempotent (guard with file existence
or the checkpoint), because the runner re-runs from the top on resume.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PARKED_EXIT_CODE = 42


class ParkSignal(Exception):
    """Raised by ctx.ask() when a question has no answer yet."""

    def __init__(self, qid: str):
        super().__init__(f"parked on question {qid}")
        self.qid = qid


@dataclass
class Outcome:
    summary: str
    artifacts: list[str] = field(default_factory=list)


@dataclass
class RunContext:
    job: Any
    job_dir: Path
    checkpoint: dict = field(default_factory=dict)

    def __post_init__(self):
        self.questions_dir = self.job_dir / "questions"
        self.answers_dir = self.job_dir / "answers"
        self.questions_dir.mkdir(exist_ok=True)
        self.answers_dir.mkdir(exist_ok=True)

    def ask(self, qid: str, prompt: str, choices: list[str] | None = None) -> str:
        """Return the human's answer, or park the job until one exists."""
        ans = self.answers_dir / f"{qid}.txt"
        if ans.exists():
            return ans.read_text(encoding="utf-8").strip()
        (self.questions_dir / f"{qid}.json").write_text(
            json.dumps({"qid": qid, "prompt": prompt, "choices": choices}, indent=2),
            encoding="utf-8",
        )
        raise ParkSignal(qid)

    def set_step(self, step: str) -> None:
        self.checkpoint["current_step"] = step


class Runner:
    """Base class. Implement run(); use ctx.ask() for human checkpoints."""

    name = "base"

    def run(self, ctx: RunContext) -> Outcome:  # pragma: no cover - interface
        raise NotImplementedError


def get_runner(job) -> Runner:
    """Route a job to a runner. Research and cloud-planned jobs go to the cloud
    agent; explicitly-local jobs to the offline executor; anything else to the demo.
    """
    from .cloud import CloudRunner
    from .demo import DemoRunner
    from .local import LocalRunner

    if job.type == "research" or job.agent == "cloud":
        return CloudRunner()
    if job.agent == "local":
        return LocalRunner()
    return DemoRunner()
