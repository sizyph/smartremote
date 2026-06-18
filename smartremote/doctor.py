"""System & config diagnostics: what works, what to fix, and the command to fix it.

`smartremote doctor` runs these read-only checks and prints a grouped checklist with
a prioritized next step. `smartremote setup` (in cli) initializes config then renders
the same checks as a guided walkthrough.
"""
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import hermes_setup, models
from .config import ROLE_HELP

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"
_SYM = {OK: "✓", WARN: "⚠", FAIL: "✗", INFO: "•"}
_COLOR = {OK: "32", WARN: "33", FAIL: "31", INFO: "90"}
_RANK = {FAIL: 0, WARN: 1, OK: 2, INFO: 3}


@dataclass
class Check:
    group: str
    name: str
    status: str
    detail: str = ""
    fix: str = ""


def run_checks(cfg: dict, root: Path) -> list[Check]:
    checks: list[Check] = []

    # --- Environment ---
    py_ok = sys.version_info >= (3, 10)
    checks.append(Check("Environment", "Python", OK if py_ok else FAIL,
                        f"{sys.version_info.major}.{sys.version_info.minor}",
                        "" if py_ok else "SmartRemote needs Python >= 3.10"))
    gpu = models.gpu_info()
    checks.append(Check("Environment", "GPU", OK if gpu else WARN,
                        gpu or "no NVIDIA GPU visible — local models would run on CPU (slow); fine for remote-only use"))

    # --- Config ---
    cfgfile = Path(root) / "config.yaml"
    checks.append(Check("Config", "config.yaml", OK if cfgfile.exists() else INFO,
                        str(cfgfile) if cfgfile.exists() else "using built-in defaults",
                        "" if cfgfile.exists() else "optional — `smartremote setup` writes a starter"))

    # --- Local models (Ollama) ---
    have = models.ollama_available()
    installed = models.ollama_list() if have else []
    checks.append(Check("Local models", "Ollama", OK if have else FAIL,
                        f"{len(installed)} model(s) pulled" if have else "not installed",
                        "" if have else "curl -fsSL https://ollama.com/install.sh | sh"))

    # --- Roles ---
    roles = cfg["models"]["roles"]
    for role in ROLE_HELP:
        r = roles.get(role) or {}
        checks.append(_check_role(role, r.get("provider", ""), r.get("model", ""), have, installed, cfg))

    # --- Notifications (Hermes) ---
    h = cfg["hermes"]
    if h.get("enabled"):
        code, body = hermes_setup.health(h["base_url"])
        checks.append(Check("Notifications", "Hermes gateway", OK if code == 200 else FAIL,
                            f"{h['base_url']} (health {code})" if code == 200 else f"unreachable: {body}",
                            "" if code == 200 else "smartremote hermes up"))
    else:
        checks.append(Check("Notifications", "Hermes", WARN, "not configured",
                            "smartremote hermes setup   (email + WhatsApp; optional but recommended)"))
    return checks


def _check_role(role: str, prov: str, model: str, have_ollama: bool, installed: list[str], cfg: dict) -> Check:
    label = f"{role} -> {prov}:{model}"
    if prov in ("local", "cline"):
        if not have_ollama:
            return Check("Roles", label, FAIL, "needs Ollama", "curl -fsSL https://ollama.com/install.sh | sh")
        if model and model not in installed:
            return Check("Roles", label, FAIL, "model not pulled", f"smartremote models pull {model}")
        if prov == "cline" and not shutil.which("cline"):
            return Check("Roles", label, FAIL, "cline CLI missing", "npm i -g cline   (then `ollama launch cline`)")
        return Check("Roles", label, OK, "ready")
    if prov == "remote":
        cmd = (cfg["models"]["remote"]["providers"].get(model) or {}).get("command", model)
        if shutil.which(cmd):
            return Check("Roles", label, OK, f"{cmd} on PATH")
        return Check("Roles", label, WARN, f"{cmd} not found",
                     f"install the {model} CLI, or: smartremote models set {role} remote <other>")
    return Check("Roles", label, WARN, f"unknown provider '{prov}'", f"smartremote models set {role} ...")


def next_step(checks: list[Check]) -> str:
    for status in (FAIL, WARN):
        for c in checks:
            if c.status == status and c.fix:
                return c.fix
    return ""


def summary(checks: list[Check]) -> str:
    n = {s: sum(1 for c in checks if c.status == s) for s in (OK, WARN, FAIL)}
    return f"{n[OK]} ok · {n[WARN]} warning(s) · {n[FAIL]} to fix"


def render(checks: list[Check], color: bool | None = None) -> None:
    color = sys.stdout.isatty() if color is None else color
    last = None
    for c in checks:
        if c.group != last:
            print(f"\n{c.group}")
            last = c.group
        sym = _SYM[c.status]
        if color:
            sym = f"\033[{_COLOR[c.status]}m{sym}\033[0m"
        print(f"  {sym} {c.name}: {c.detail}")
        if c.fix and c.status in (FAIL, WARN):
            print(f"      -> {c.fix}")
    print(f"\n{summary(checks)}")
    nxt = next_step(checks)
    if nxt:
        print(f"Next:  {nxt}")
