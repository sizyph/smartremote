"""Hermetic end-to-end test of the plan -> approve -> execute -> guard pipeline.

Forces mock providers (SMARTREMOTE_FAKE_LLM=1) so it runs fully offline. Proves:
ingest -> plan -> park on approval -> human answers -> execute -> guard -> done.
Run with `python -m smartremote.cli selftest`.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

from . import state as st
from .config import load_config
from .dispatcher import Dispatcher

JOB = """---
id: selftest-demo
title: Self-test plan/execute/guard pipeline
type: build
agent: cloud
gpu: none
deploy_target: jetson
needs_human: true
notify: {on_done: none, on_question: none, on_fail: none}
---
# Goal
Exercise plan -> approve -> execute -> guard end to end (mock models).
"""


def _drain(disp: Dispatcher, timeout: float = 15.0) -> None:
    disp.schedule()
    deadline = time.monotonic() + timeout
    while disp.running and time.monotonic() < deadline:
        disp.reap()
        if disp.running:
            time.sleep(0.05)


def run_selftest() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="smartremote-selftest-"))
    prev = os.environ.get("SMARTREMOTE_FAKE_LLM")
    os.environ["SMARTREMOTE_FAKE_LLM"] = "1"  # inherited by the run_job subprocess
    job_dir = tmp / "jobs" / "selftest-demo"
    try:
        disp = Dispatcher(tmp, load_config(None))
        (tmp / "inbox" / "selftest-demo.md").write_text(JOB, encoding="utf-8")
        disp.ingest()

        _drain(disp)  # plan (mock) then park on approval
        data = st.Status(job_dir).read()
        assert data["state"] == st.WAITING_HUMAN, f"expected waiting_human, got {data['state']}"
        assert data["pending_question"] == "approve-plan", data["pending_question"]
        assert (job_dir / "artifacts" / "plan.md").exists(), "planner did not write plan.md"
        print("PASS  planned and parked on approval")

        (job_dir / "answers" / "approve-plan.txt").write_text("approve", encoding="utf-8")
        _drain(disp)  # resume -> execute -> guard -> done
        data = st.Status(job_dir).read()
        assert data["state"] == st.DONE, f"expected done, got {data['state']}"
        arts = data["result"]["artifacts"]
        assert "artifacts/plan.md" in arts and "artifacts/result.md" in arts, arts
        print(f"PASS  executed + guarded; artifacts={arts}")
        print("SELFTEST OK")
    finally:
        if prev is None:
            os.environ.pop("SMARTREMOTE_FAKE_LLM", None)
        else:
            os.environ["SMARTREMOTE_FAKE_LLM"] = prev
        shutil.rmtree(tmp, ignore_errors=True)
