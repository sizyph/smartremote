"""Smoke tests: the contract, the park/resume cycle, and scheduler invariants."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from smartremote import state as st
from smartremote.config import load_config
from smartremote.dispatcher import Dispatcher
from smartremote.job import JobError, parse_job
from smartremote.selftest import run_selftest


def test_park_resume_selftest():
    # Drives ingest -> park-on-question -> answer -> resume -> done; asserts inside.
    run_selftest()


def test_job_validation():
    good = parse_job("---\nid: x\ntype: build\nagent: local\ngpu: none\n---\n# Goal\nhi\n")
    assert good.id == "x" and good.gpu == "none"
    with pytest.raises(JobError):
        parse_job("no frontmatter at all")
    with pytest.raises(JobError):
        parse_job("---\nid: x\ntype: bogus\nagent: local\ngpu: none\n---\n# g\nx\n")


def _mk(tmp: Path, jid: str, gpu: str, deps=None):
    (tmp / "inbox" / f"{jid}.md").write_text(
        f"---\nid: {jid}\ntype: build\nagent: local\ngpu: {gpu}\n"
        f"depends_on: {deps or []}\n"
        f"notify: {{on_done: none, on_question: none, on_fail: none}}\n---\n# Goal\nx\n",
        encoding="utf-8",
    )


def test_scheduler_invariants():
    tmp = Path(tempfile.mkdtemp(prefix="sr-test-"))
    try:
        disp = Dispatcher(tmp, load_config(None))  # max_parallel_cpu_jobs = 3
        for n in (1, 2):
            _mk(tmp, f"gpu{n}", "required")
        for n in (1, 2, 3, 4):
            _mk(tmp, f"cpu{n}", "none")
        _mk(tmp, "dep1", "none", deps=["gpu1"])

        disp.ingest()
        disp.schedule()  # inspect launch decisions before reaping
        launched = set(disp.running)
        gpu = {j for j in launched if j.startswith("gpu")}
        cpu = {j for j in launched if j.startswith("cpu")}

        assert len(gpu) == 1, f"GPU must serialize to 1, got {gpu}"
        assert disp.gpu.holder() in gpu, "GPU lock not held by the launched gpu job"
        assert len(cpu) == 3, f"CPU must cap at max_parallel=3, got {cpu}"
        assert st.Status(tmp / "jobs" / "dep1").read()["state"] == "blocked"
    finally:
        for p in disp.running.values():
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()
        shutil.rmtree(tmp, ignore_errors=True)
