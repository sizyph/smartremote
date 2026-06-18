"""Publish a finished job's artifacts and return shareable links.

Routes each file under jobs/<id>/artifacts/ to a backend:
  - git    : commit small text/code into a *private* results repo (a local clone)
  - rclone : upload large blobs to Drive/S3/... and make a shareable link
  - local  : leave them on the server (default; pull with rsync/sftp)
  - auto   : size-routed — small files -> git, large files -> rclone

The git repo doubles as the index: a PUBLISHED.md manifest links out to the blobs.
Called by the dispatcher when a job hits `done`; the links are appended to the
Hermes completion message. Configure under `publish:` (see config.DEFAULTS).

Per-backend failures are recorded as `error` entries rather than aborting the rest.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_GIT_ID = ["-c", "user.email=smartremote@localhost", "-c", "user.name=SmartRemote"]


class PublishError(RuntimeError):
    pass


@dataclass
class Published:
    name: str
    where: str  # git | rclone | local | error
    url: str


def _git(repo: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise PublishError(f"git {args[0]} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def _run(args: list[str]) -> str:
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise PublishError(f"{args[0]} failed: {r.stderr.strip()[:300]}")
    return r.stdout


class GitPublisher:
    """Commit artifacts into a local clone of a (private) results repo, then push."""

    def __init__(self, gcfg: dict):
        gcfg = gcfg or {}
        self.repo_dir = Path(gcfg["repo_dir"]).expanduser() if gcfg.get("repo_dir") else None
        self.remote = gcfg.get("remote", "")
        self.branch = gcfg.get("branch", "main")
        self.push = gcfg.get("push", True)

    def publish(self, job_id: str, files: list[Path], artifacts_dir: Path) -> list[Published]:
        if not self.repo_dir:
            raise PublishError("publish.git.repo_dir not set — clone your PRIVATE results repo and point it there")
        if not (self.repo_dir / ".git").exists():
            raise PublishError(f"{self.repo_dir} is not a git repo — `git clone <your-private-results-repo>` there first")
        dest = self.repo_dir / job_id
        for f in files:
            target = dest / f.relative_to(artifacts_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
        _git(self.repo_dir, "add", job_id)
        _git(self.repo_dir, *_GIT_ID, "commit", "-m", f"results: {job_id}", check=False)
        if self.push and self.remote:
            _git(self.repo_dir, "push", "origin", self.branch, check=False)
        base = self._web_base()
        return [Published(str(f.relative_to(artifacts_dir)), "git",
                          f"{base}/{job_id}/{f.relative_to(artifacts_dir)}" if base
                          else str(dest / f.relative_to(artifacts_dir)))
                for f in files]

    def _web_base(self) -> str:
        m = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?$", self.remote or "")
        return f"https://github.com/{m.group(1)}/{m.group(2)}/tree/{self.branch}" if m else ""


class RclonePublisher:
    """Upload artifacts to an rclone remote (Drive/S3/...) and make shareable links."""

    def __init__(self, rcfg: dict):
        rcfg = rcfg or {}
        self.remote = rcfg.get("remote", "")
        self.link = rcfg.get("link", True)

    def publish(self, job_id: str, files: list[Path], artifacts_dir: Path) -> list[Published]:
        if not shutil.which("rclone"):
            raise PublishError("rclone not installed — https://rclone.org/install/")
        if not self.remote:
            raise PublishError("publish.rclone.remote not set — e.g. 'gdrive:smartremote-results'")
        out = []
        for f in files:
            rel = f.relative_to(artifacts_dir)
            dest = f"{self.remote.rstrip('/')}/{job_id}/{rel}"
            _run(["rclone", "copyto", str(f), dest])
            url = dest
            if self.link:
                try:
                    url = _run(["rclone", "link", dest]).strip() or dest
                except PublishError:
                    pass
            out.append(Published(str(rel), "rclone", url))
        return out


def _manifest(job_id: str, published: list[Published], git_files: list[Path], artifacts: Path) -> str:
    lines = [f"# Published artifacts — {job_id}", ""]
    for p in published:
        lines.append(f"- `{p.name}` ({p.where}): {p.url}")
    for f in git_files:
        rel = f.relative_to(artifacts)
        lines.append(f"- `{rel}` (git): ./{rel}")
    return "\n".join(lines) + "\n"


def publish_job(cfg: dict, job_id: str, job_dir) -> list[Published]:
    pcfg = cfg.get("publish", {}) or {}
    backend = pcfg.get("backend", "local")
    if backend == "local":
        return []
    artifacts = Path(job_dir) / "artifacts"
    if not artifacts.exists():
        return []
    files = sorted(f for f in artifacts.rglob("*") if f.is_file() and f.name != "PUBLISHED.md")
    if not files:
        return []

    threshold = float(pcfg.get("size_threshold_mb", 25)) * 1_000_000
    git_files: list[Path] = []
    rclone_files: list[Path] = []
    local_files: list[Path] = []
    for f in files:
        route = backend
        if backend == "auto":
            route = "rclone" if f.stat().st_size > threshold else "git"
        {"git": git_files, "rclone": rclone_files}.get(route, local_files).append(f)

    out: list[Published] = []
    if rclone_files:
        try:
            out += RclonePublisher(pcfg.get("rclone", {})).publish(job_id, rclone_files, artifacts)
        except PublishError as e:
            out.append(Published("(rclone)", "error", str(e)))
    out += [Published(str(f.relative_to(artifacts)), "local", str(f)) for f in local_files]

    if git_files:
        manifest = artifacts / "PUBLISHED.md"
        manifest.write_text(_manifest(job_id, out, git_files, artifacts), encoding="utf-8")
        try:
            out += GitPublisher(pcfg.get("git", {})).publish(job_id, [*git_files, manifest], artifacts)
        except PublishError as e:
            out.append(Published("(git)", "error", str(e)))
    return out
