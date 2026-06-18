"""The dispatcher: a dumb, deterministic supervisor loop (no model calls here).

Each tick it:
  * ingests inbox/*.md          -> jobs/<id>/ workspace + status.json
  * recovers jobs left RUNNING by a previous crash
  * reaps finished run_job subprocesses, mapping exit codes to states + notifications
  * schedules: respects depends_on; serializes gpu:required behind the GPU lock;
    runs gpu:none jobs in parallel up to max_parallel_cpu_jobs; resumes answered jobs
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import job as jobmod
from . import state as st
from .hermes import build_notifier
from .runners import PARKED_EXIT_CODE

# Directory containing the `smartremote` package — used as the subprocess cwd so
# `python -m smartremote.run_job` resolves regardless of where the data root is.
_CODE_ROOT = Path(__file__).resolve().parent.parent


def _chan(data: dict, key: str) -> str:
    return (data.get("notify") or {}).get(key, "email")


def _result_body(data: dict) -> str:
    r = data.get("result") or {}
    arts = "\n".join(f"  - {a}" for a in r.get("artifacts", [])) or "  (none)"
    return f"{r.get('summary', '(no summary)')}\n\nArtifacts:\n{arts}"


class Dispatcher:
    def __init__(self, root: Path, cfg: dict):
        self.root = Path(root).resolve()
        self.cfg = cfg
        self.inbox = self.root / "inbox"
        self.jobs = self.root / "jobs"
        self.processed = self.inbox / ".processed"
        self.gpu = st.GpuLock(self.root / "gpu.lock")
        self.notifier = build_notifier(cfg)
        self.poll = float(cfg.get("poll_interval_seconds", 2))
        self.max_parallel = int(cfg.get("max_parallel_cpu_jobs", 3))
        self.running: dict[str, subprocess.Popen] = {}
        for d in (self.inbox, self.jobs, self.processed):
            d.mkdir(parents=True, exist_ok=True)

    def log(self, msg: str) -> None:
        print(f"[{st.utcnow()}] {msg}", flush=True)

    # ---- ingest -------------------------------------------------------
    def ingest(self) -> None:
        for f in sorted(self.inbox.glob("*.md")):
            if f.name.startswith("."):
                continue
            try:
                job = jobmod.load_job_file(f)
            except jobmod.JobError as e:
                shutil.move(str(f), str(self.processed / (f.name + ".invalid")))
                self.notifier.send(
                    channel="email", subject=f"Rejected job {f.name}",
                    body=str(e), job_id=f.stem,
                )
                self.log(f"rejected {f.name}: {e}")
                continue
            job_dir = self.jobs / job.id
            if job_dir.exists():  # duplicate id — archive and skip
                shutil.move(str(f), str(self.processed / f.name))
                self.log(f"duplicate id {job.id}; archived {f.name}")
                continue
            (job_dir / "workspace").mkdir(parents=True)
            (job_dir / "artifacts").mkdir()
            (job_dir / "logs").mkdir()
            shutil.copy2(f, job_dir / "request.md")
            status = st.Status(job_dir)
            status.init(job)
            status.transition(st.BLOCKED if job.depends_on else st.QUEUED, "ingested")
            shutil.move(str(f), str(self.processed / f.name))
            self.log(f"ingested {job.id} (type={job.type} gpu={job.gpu})")

    # ---- helpers ------------------------------------------------------
    def _all_status(self) -> dict:
        out = {}
        if self.jobs.exists():
            for d in self.jobs.iterdir():
                s = st.Status(d)
                if s.exists():
                    out[d.name] = (d, s, s.read())
        return out

    def _deps_done(self, data: dict, all_status: dict) -> bool:
        for dep in data.get("depends_on") or []:
            t = all_status.get(dep)
            if not t or t[2]["state"] != st.DONE:
                return False
        return True

    # ---- recovery -----------------------------------------------------
    def recover(self) -> None:
        for _, s, data in self._all_status().values():
            if data["state"] == st.RUNNING:
                if data["gpu"] == "required":
                    self.gpu.release(data["id"])
                s.transition(st.QUEUED, "recovered after dispatcher restart")
                self.log(f"recovered {data['id']} -> queued")

    # ---- supervise ----------------------------------------------------
    def reap(self) -> None:
        for jid, proc in list(self.running.items()):
            rc = proc.poll()
            if rc is None:
                continue
            del self.running[jid]
            job_dir = self.jobs / jid
            data = st.Status(job_dir).read()
            if data["gpu"] == "required":
                self.gpu.release(jid)
            if rc == PARKED_EXIT_CODE:
                self._notify_question(job_dir, data)
            elif rc == 0:
                self.notifier.send(
                    channel=_chan(data, "on_done"), subject=f"[done] {jid}",
                    body=_result_body(data) + self._publish(jid, job_dir), job_id=jid,
                )
                self.log(f"{jid} done")
            else:
                self.notifier.send(
                    channel=_chan(data, "on_fail"), subject=f"[failed] {jid}",
                    body=(data.get("error") or "")[:1000], job_id=jid,
                )
                self.log(f"{jid} failed (rc={rc})")

    def _notify_question(self, job_dir: Path, data: dict) -> None:
        jid = data["id"]
        qid = data.get("pending_question")
        qfile = job_dir / "questions" / f"{qid}.json"
        prompt = json.loads(qfile.read_text())["prompt"] if qfile.exists() else "(see job)"
        self.notifier.send(
            channel=_chan(data, "on_question"),
            subject=f"[input needed] {jid} ({qid})",
            body=f"{prompt}\n\nReply: smartremote answer {jid} {qid} \"<your answer>\"",
            job_id=jid,
        )
        self.log(f"{jid} parked on {qid}")

    def _publish(self, jid: str, job_dir: Path) -> str:
        """Publish artifacts per config; return a links block for the notification."""
        if (self.cfg.get("publish") or {}).get("backend", "local") == "local":
            return ""
        try:
            from .publish import publish_job

            pubs = publish_job(self.cfg, jid, job_dir)
        except Exception as e:  # noqa: BLE001
            self.log(f"{jid} publish error: {e}")
            return f"\n\n(publish failed: {e})"
        if not pubs:
            return ""
        self.log(f"{jid} published {len(pubs)} artifact(s)")
        return "\n\nPublished:\n" + "\n".join(f"  {p.name}: {p.url}" for p in pubs)

    # ---- schedule -----------------------------------------------------
    def schedule(self) -> None:
        all_status = self._all_status()
        for _, s, data in all_status.values():
            if data["state"] == st.BLOCKED and self._deps_done(data, all_status):
                data.update(s.transition(st.QUEUED, "deps satisfied"))
            elif data["state"] == st.WAITING_HUMAN:
                qid = data.get("pending_question")
                if qid and (self.jobs / data["id"] / "answers" / f"{qid}.txt").exists():
                    data.update(s.transition(st.QUEUED, f"answer to {qid} received"))

        # Order: priority, then submission time, then id (deterministic tiebreak).
        # created_at is second-resolution, so strict FIFO within one second is not
        # guaranteed — use `priority` for ordering you care about.
        ready = sorted(
            (t for t in all_status.values()
             if t[2]["state"] == st.QUEUED and t[2]["id"] not in self.running),
            key=lambda t: (t[2].get("priority", 100), t[2]["created_at"], t[2]["id"]),
        )
        for job_dir, _, data in ready:
            jid = data["id"]
            if data["gpu"] == "required":
                if self.gpu.holder() is not None or not self.gpu.acquire(jid):
                    continue
            else:
                cpu_running = sum(
                    1 for r in self.running
                    if all_status.get(r) and all_status[r][2]["gpu"] != "required"
                )
                if cpu_running >= self.max_parallel:
                    continue
            self._launch(job_dir, jid)

    def _launch(self, job_dir: Path, jid: str) -> None:
        log_f = (job_dir / "logs" / "runner.log").open("a")
        proc = subprocess.Popen(
            [sys.executable, "-m", "smartremote.run_job", str(job_dir.resolve())],
            stdout=log_f, stderr=subprocess.STDOUT, cwd=str(_CODE_ROOT),
        )
        self.running[jid] = proc
        self.log(f"launched {jid} (pid {proc.pid})")

    # ---- loop ---------------------------------------------------------
    def tick(self) -> None:
        self.ingest()
        self.reap()
        self.schedule()

    def run_forever(self) -> None:
        self.recover()
        self.log(
            f"dispatcher up at {self.root} (poll {self.poll}s, "
            f"notifier={type(self.notifier).__name__})"
        )
        while True:
            self.tick()
            time.sleep(self.poll)
