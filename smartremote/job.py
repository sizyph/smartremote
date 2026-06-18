"""The job contract: parse + validate a SmartRemote job Markdown file.

A job file is Markdown with a YAML frontmatter block delimited by `---`. The
frontmatter is the machine-readable routing contract (id, type, agent, gpu...);
the body is the human/agent instructions (goal, acceptance criteria, inputs).
See docs/job-format.md for the full spec.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import yaml

TYPES = {"train", "research", "build", "pipeline"}
AGENTS = {"cloud", "local"}
GPU = {"required", "none"}
CHANNELS = {"email", "whatsapp", "none"}
DEPLOY_TARGETS = {"jetson", "server", "arm", "mcu", "none"}
RUNNERS = {"", "scout", "cloud", "plan-execute"}  # "" = route by type

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")  # 1-64 chars, lowercase
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


class JobError(ValueError):
    """Raised when a job file is malformed or fails validation."""


@dataclasses.dataclass
class Notify:
    on_done: str = "email"
    on_question: str = "whatsapp"
    on_fail: str = "email"

    def validate(self) -> None:
        for field, val in dataclasses.asdict(self).items():
            if val not in CHANNELS:
                raise JobError(f"notify.{field}={val!r} not in {sorted(CHANNELS)}")


@dataclasses.dataclass
class Budget:
    wallclock_hours: float | None = None
    tokens: int | None = None


@dataclasses.dataclass
class Job:
    id: str
    title: str
    type: str
    agent: str
    gpu: str
    body: str
    priority: int = 100
    needs_human: bool = False
    notify: Notify = dataclasses.field(default_factory=Notify)
    budget: Budget = dataclasses.field(default_factory=Budget)
    depends_on: list[str] = dataclasses.field(default_factory=list)
    deploy_target: str = "none"
    runner: str = ""  # force a specific runner; "" routes by type
    source_path: str | None = None

    def validate(self) -> None:
        if not _ID_RE.match(self.id):
            raise JobError(f"invalid id {self.id!r}: must match {_ID_RE.pattern}")
        if self.type not in TYPES:
            raise JobError(f"type={self.type!r} not in {sorted(TYPES)}")
        if self.agent not in AGENTS:
            raise JobError(f"agent={self.agent!r} not in {sorted(AGENTS)}")
        if self.gpu not in GPU:
            raise JobError(f"gpu={self.gpu!r} not in {sorted(GPU)}")
        if self.deploy_target not in DEPLOY_TARGETS:
            raise JobError(
                f"deploy_target={self.deploy_target!r} not in {sorted(DEPLOY_TARGETS)}"
            )
        if self.runner not in RUNNERS:
            raise JobError(f"runner={self.runner!r} not in {sorted(RUNNERS)}")
        if not isinstance(self.depends_on, list) or not all(
            isinstance(x, str) for x in self.depends_on
        ):
            raise JobError("depends_on must be a list of job ids")
        self.notify.validate()
        if not self.body.strip():
            raise JobError("job body is empty: nothing for the agent to do")


def _slug_from_filename(path: Path) -> str:
    stem = re.sub(r"[^a-z0-9._-]+", "-", path.stem.lower()).strip("-.")
    return stem or "job"


def parse_job(
    text: str, *, source_path: str | None = None, default_id: str | None = None
) -> Job:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise JobError("missing YAML frontmatter (file must start with '---')")
    raw, body = m.group(1), m.group(2)
    try:
        meta = yaml.safe_load(raw) or {}
    except yaml.YAMLError as e:
        raise JobError(f"frontmatter is not valid YAML: {e}") from e
    if not isinstance(meta, dict):
        raise JobError("frontmatter must be a YAML mapping")

    notify_raw = meta.get("notify") or {}
    budget_raw = meta.get("budget") or {}
    if not isinstance(notify_raw, dict):
        raise JobError("notify must be a mapping")
    if not isinstance(budget_raw, dict):
        raise JobError("budget must be a mapping")

    job = Job(
        id=str(meta.get("id") or default_id or "").strip(),
        title=str(meta.get("title") or "").strip() or "(untitled)",
        type=str(meta.get("type") or "").strip(),
        agent=str(meta.get("agent") or "").strip(),
        gpu=str(meta.get("gpu") or "none").strip(),
        body=body,
        priority=int(meta.get("priority", 100)),
        needs_human=bool(meta.get("needs_human", False)),
        notify=Notify(
            on_done=str(notify_raw.get("on_done", "email")),
            on_question=str(notify_raw.get("on_question", "whatsapp")),
            on_fail=str(notify_raw.get("on_fail", "email")),
        ),
        budget=Budget(
            wallclock_hours=budget_raw.get("wallclock_hours"),
            tokens=budget_raw.get("tokens"),
        ),
        depends_on=list(meta.get("depends_on") or []),
        deploy_target=str(meta.get("deploy_target") or "none").strip(),
        runner=str(meta.get("runner") or "").strip(),
        source_path=source_path,
    )
    if not job.id:
        raise JobError("missing 'id' and no default could be derived")
    job.validate()
    return job


def load_job_file(path: str | Path) -> Job:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    return parse_job(text, source_path=str(p), default_id=_slug_from_filename(p))
