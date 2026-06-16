"""Hermetic end-to-end test of the park/resume cycle, in a throwaway temp dir.

Proves: ingest -> run -> park on a question -> human answers -> resume -> done.
Run with `python -m smartremote.cli selftest`.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from . import state as st
from .config import load_config
from .dispatcher import Dispatcher

JOB = """---
id: selftest-demo
title: Self-test plan-approval loop
type: build
agent: cloud
gpu: none
deploy_target: jetson
notify: {on_done: none, on_question: none, on_fail: none}
---
# Goal
Exercise the cloud-plan -> human approval -> finish flow end to end.
"""


def _drain(disp: Dispatcher, timeout: float = 15.0) -> None:
    """Run schedule, then reap until no subprocess is in flight."""
    disp.schedule()
    deadline = time.monotonic() + timeout
    while disp.running and time.monotonic() < deadline:
        disp.reap()
        if disp.running:
            time.sleep(0.05)


def run_selftest() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="smartremote-selftest-"))
    try:
        disp = Dispatcher(tmp, load_config(None))
        (tmp / "inbox" / "selftest-demo.md").write_text(JOB, encoding="utf-8")
        disp.ingest()

        _drain(disp)  # runs until it parks on the approval question
        s = st.Status(tmp / "jobs" / "selftest-demo")
        data = s.read()
        assert data["state"] == st.WAITING_HUMAN, f"expected waiting_human, got {data['state']}"
        qid = data["pending_question"]
        assert qid, "expected a pending question"
        print(f"PASS  parked on question {qid!r}")

        # Human answers via the same path `smartremote answer` would use.
        (tmp / "jobs" / "selftest-demo" / "answers" / f"{qid}.txt").write_text(
            "approve", encoding="utf-8"
        )
        _drain(disp)  # resumes and completes
        data = s.read()
        assert data["state"] == st.DONE, f"expected done, got {data['state']}"
        assert data["result"]["artifacts"] == ["artifacts/plan.md"], data["result"]
        print(f"PASS  resumed and completed; artifacts={data['result']['artifacts']}")
        print("SELFTEST OK")
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)
