"""Model roles, Ollama integration, and hardware-aware recommendations.

Roles (see config.ROLE_HELP):
  planner -> remote (Claude Code / Codex): writes the best plan
  executor -> local (Ollama): applies the plan
  guard -> checks the executor's output against the plan
  escalation -> remote takes over when local struggles, or proposes a new local model

The catalog below is curated for a single 24 GB GPU (sizes are ~Q4). The real
"best now" should come from the model-scout job; this is a sane starting set.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class Rec:
    tag: str  # Ollama tag
    params: str
    role: str  # primary role hint
    vram_q4_gb: float
    note: str


# Fits a 24 GB card at ~Q4 (+ KV cache). Verify exact tags against the Ollama library.
RECOMMENDED = [
    Rec("qwen3-coder:32b", "32B", "executor", 19, "Best coding all-rounder that fits; ~50 tok/s @ Q4."),
    Rec("devstral:24b", "24B", "executor", 14, "Agentic coding (tool calls, multi-file edits) — ideal for plan execution."),
    Rec("qwen3:30b-a3b", "30B MoE (3B active)", "executor", 18, "Fastest (~150 tok/s) with good quality."),
    Rec("deepseek-r1:32b", "32B", "guard", 19, "Strong reasoning — good for checking the executor."),
    Rec("qwen3:14b", "14B", "executor", 9, "Light daily driver; lots of context headroom."),
]


def ollama_available() -> bool:
    return shutil.which("ollama") is not None


def ollama_list() -> list[str]:
    """Names of locally-pulled Ollama models ([] if Ollama is absent/unreachable)."""
    if not ollama_available():
        return []
    try:
        out = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
    except Exception:
        return []
    names = []
    for line in out.stdout.splitlines()[1:]:  # skip header row
        parts = line.split()
        if parts:
            names.append(parts[0])
    return names


def ollama_pull(tag: str) -> int:
    if not ollama_available():
        print("ollama not found. Install it:  curl -fsSL https://ollama.com/install.sh | sh")
        return 1
    return subprocess.call(["ollama", "pull", tag])


def remote_provider_status(cfg: dict) -> dict:
    """{provider_id: is_cli_on_PATH} for the configured remote providers."""
    out = {}
    providers = (cfg.get("models", {}).get("remote", {}) or {}).get("providers", {}) or {}
    for pid, p in providers.items():
        cmd = (p or {}).get("command", "")
        out[pid] = bool(cmd and shutil.which(cmd))
    return out


def gpu_info() -> str | None:
    """One line per GPU: 'name, total, used' — or None if no NVIDIA GPU is visible."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def role_model(cfg: dict, role: str) -> tuple[str, str] | None:
    """Return (provider, model) assigned to `role`, or None."""
    r = (cfg.get("models", {}).get("roles", {}) or {}).get(role)
    if not r:
        return None
    return r.get("provider", ""), r.get("model", "")
