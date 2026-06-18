"""Subprocess entry: run (or resume) a single job. The dispatcher launches this.

Exit codes:
  0   done
  42  parked (a question is pending; see jobs/<id>/questions/)
  1   failed
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from . import job as jobmod
from . import state as st
from .config import load_config
from .runners import PARKED_EXIT_CODE, ParkSignal, RunContext, get_runner


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m smartremote.run_job <job_dir>", file=sys.stderr)
        return 2
    job_dir = Path(argv[1]).resolve()
    status = st.Status(job_dir)
    data = status.read()
    job = jobmod.load_job_file(job_dir / "request.md")

    status.update(attempts=data.get("attempts", 0) + 1)
    status.transition(st.RUNNING, "runner started")

    cfg = load_config(job_dir.parent.parent / "config.yaml")
    ctx = RunContext(job=job, job_dir=job_dir, checkpoint=data.get("checkpoint") or {}, cfg=cfg)
    runner = get_runner(job)
    try:
        outcome = runner.run(ctx)
    except ParkSignal as p:
        status.update(checkpoint=ctx.checkpoint, pending_question=p.qid)
        status.transition(st.WAITING_HUMAN, f"awaiting answer to {p.qid}")
        return PARKED_EXIT_CODE
    except Exception as e:  # noqa: BLE001
        status.update(error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        status.transition(st.FAILED, "runner raised")
        return 1

    status.update(
        result={"summary": outcome.summary, "artifacts": outcome.artifacts},
        checkpoint=ctx.checkpoint,
        pending_question=None,
    )
    status.transition(st.DONE, "runner completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
