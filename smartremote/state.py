"""Per-job state (status.json), lifecycle transitions, and the single-GPU lock.

One RTX 4090 => at most one `gpu: required` job runs at a time. The lock is a file
created atomically with O_CREAT|O_EXCL; the holder records its job id + pid so a
stale lock can be diagnosed. `gpu: none` jobs ignore the lock and run in parallel.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
from pathlib import Path

# Lifecycle states.
RECEIVED = "received"
BLOCKED = "blocked"  # waiting on depends_on
QUEUED = "queued"
RUNNING = "running"
WAITING_HUMAN = "waiting_human"
DONE = "done"
FAILED = "failed"

TERMINAL = {DONE, FAILED}


def utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomic on the same filesystem


class Status:
    """Reads/writes jobs/<id>/status.json with a small transition helper."""

    def __init__(self, job_dir: Path):
        self.job_dir = Path(job_dir)
        self.path = self.job_dir / "status.json"

    def exists(self) -> bool:
        return self.path.exists()

    def read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def init(self, job) -> dict:
        now = utcnow()
        data = {
            "id": job.id,
            "title": job.title,
            "type": job.type,
            "agent": job.agent,
            "gpu": job.gpu,
            "priority": job.priority,
            "depends_on": job.depends_on,
            "deploy_target": job.deploy_target,
            "notify": {
                "on_done": job.notify.on_done,
                "on_question": job.notify.on_question,
                "on_fail": job.notify.on_fail,
            },
            "state": RECEIVED,
            "created_at": now,
            "updated_at": now,
            "attempts": 0,
            "current_step": None,
            "checkpoint": {},
            "pending_question": None,
            "history": [],
            "result": None,
            "error": None,
        }
        _atomic_write_json(self.path, data)
        return data

    def update(self, **changes) -> dict:
        data = self.read()
        data.update(changes)
        data["updated_at"] = utcnow()
        _atomic_write_json(self.path, data)
        return data

    def transition(self, new_state: str, note: str = "") -> dict:
        data = self.read()
        data["history"].append({"state": new_state, "at": utcnow(), "note": note})
        data["state"] = new_state
        data["updated_at"] = utcnow()
        _atomic_write_json(self.path, data)
        return data


class GpuLock:
    """Atomic single-holder lock for the one GPU."""

    def __init__(self, lock_path: Path):
        self.path = Path(lock_path)

    def acquire(self, holder: str) -> bool:
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w") as f:
            json.dump({"holder": holder, "pid": os.getpid(), "at": utcnow()}, f)
        return True

    def release(self, holder: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            info = json.loads(self.path.read_text(encoding="utf-8"))
            if info.get("holder") == holder:
                self.path.unlink()

    def holder(self) -> str | None:
        with contextlib.suppress(FileNotFoundError):
            return json.loads(self.path.read_text(encoding="utf-8")).get("holder")
        return None
