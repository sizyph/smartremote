"""Model providers behind the role abstraction.

A provider answers `complete(prompt, system=...)` with text. Roles are resolved
to a provider from config:
  - "remote" -> a headless frontier-agent CLI. Claude Code: `claude -p` (prompt on
    stdin); Codex: `codex exec`. Command/args are configurable per provider.
  - "local"  -> Ollama HTTP API (/api/generate).
  - "mock"   -> deterministic canned text (tests / dry runs).

Set env SMARTREMOTE_FAKE_LLM=1 to force every role to the mock provider — used by
the self-test so the full plan->execute->guard->escalate pipeline runs offline.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.request

REMOTE_TIMEOUT = int(os.environ.get("SMARTREMOTE_REMOTE_TIMEOUT", "1800"))
LOCAL_TIMEOUT = int(os.environ.get("SMARTREMOTE_LOCAL_TIMEOUT", "600"))

# How to call each known remote CLI in non-interactive mode; prompt goes on stdin.
_DEFAULT_CLI_ARGS = {"claude": ["-p"], "codex": ["exec"]}


class ProviderError(RuntimeError):
    pass


class RemoteCliProvider:
    """Headless frontier-agent CLI (Claude Code / Codex). Prompt is fed on stdin."""

    def __init__(self, provider_id: str, pcfg: dict):
        self.id = provider_id
        self.command = (pcfg or {}).get("command") or provider_id
        self.args = (pcfg or {}).get("args") or _DEFAULT_CLI_ARGS.get(self.command, [])

    def complete(self, prompt: str, *, system: str | None = None, workspace=None) -> str:
        if not shutil.which(self.command):
            raise ProviderError(
                f"remote agent CLI '{self.command}' not on PATH (role provider '{self.id}'). "
                "Install it, or reassign the role with `smartremote models set`.")
        text = f"{system}\n\n{prompt}" if system else prompt
        try:
            out = subprocess.run(
                [self.command, *self.args], input=text, capture_output=True, text=True,
                cwd=str(workspace) if workspace else None, timeout=REMOTE_TIMEOUT)
        except subprocess.TimeoutExpired as e:
            raise ProviderError(f"{self.command} timed out after {REMOTE_TIMEOUT}s") from e
        if out.returncode != 0:
            raise ProviderError(f"{self.command} exited {out.returncode}: {out.stderr.strip()[:500]}")
        return out.stdout.strip()


class OllamaProvider:
    """Local model via the Ollama HTTP API."""

    def __init__(self, model: str, base_url: str):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def complete(self, prompt: str, *, system: str | None = None, workspace=None) -> str:
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        req = urllib.request.Request(
            f"{self.base_url}/api/generate", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=LOCAL_TIMEOUT) as r:  # noqa: S310
                return json.loads(r.read()).get("response", "").strip()
        except Exception as e:  # noqa: BLE001
            raise ProviderError(
                f"Ollama call failed (model '{self.model}' @ {self.base_url}): {e}. "
                "Is the model pulled and `ollama serve` running?") from e


class MockProvider:
    """Deterministic, offline; varies by role so the pipeline produces sensible text."""

    def __init__(self, role: str):
        self.role = role

    def complete(self, prompt: str, *, system: str | None = None, workspace=None) -> str:
        if self.role == "planner":
            return "# Plan (mock)\n\n1. do the thing\n2. verify the thing\n"
        if self.role == "executor":
            return "Applied steps 1-2 (mock executor output)."
        if self.role == "guard":
            if os.environ.get("SMARTREMOTE_FAKE_GUARD") == "fail":
                return '{"ok": false, "issues": ["mock: step 2 not satisfied"], "summary": "needs rework"}'
            return '{"ok": true, "issues": [], "summary": "result matches the plan"}'
        if self.role == "escalation":
            return "Escalation (mock): reworked the task to satisfy the plan."
        return f"[mock {self.role}]"


def provider_for_role(cfg: dict, role: str):
    if os.environ.get("SMARTREMOTE_FAKE_LLM"):
        return MockProvider(role)
    rc = (cfg.get("models", {}).get("roles", {}) or {}).get(role)
    if not rc:
        raise ProviderError(f"no model assigned to role '{role}' (set it with `smartremote models set`)")
    provider, model = rc.get("provider"), rc.get("model")
    if provider == "mock":
        return MockProvider(role)
    if provider == "local":
        base = cfg.get("models", {}).get("local", {}).get("base_url", "http://127.0.0.1:11434")
        return OllamaProvider(model, base)
    if provider == "remote":
        providers = cfg.get("models", {}).get("remote", {}).get("providers", {}) or {}
        return RemoteCliProvider(model, providers.get(model, {}))
    raise ProviderError(f"role '{role}' has unknown provider '{provider}'")


def parse_verdict(text: str) -> dict:
    """Lenient parse of a guard verdict: {ok, issues, summary}.

    Unparseable output defaults to ok=True (with a note) to avoid spurious escalation.
    """
    for candidate in (text, _first_json_object(text)):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, dict) and "ok" in obj:
            return {"ok": bool(obj["ok"]), "issues": obj.get("issues", []), "summary": obj.get("summary", "")}
    return {"ok": True, "issues": ["guard output not parseable as JSON"], "summary": text.strip()[:200]}


def _first_json_object(text: str) -> str | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else None
