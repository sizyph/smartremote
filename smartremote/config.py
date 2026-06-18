"""Layered configuration.

Two files, deep-merged in order:
  1. <root>/config.yaml             - hand-edited by you (preserved, never rewritten)
  2. <root>/smartremote.local.yaml  - written by the CLI (`models`, `hermes` commands)

Built-in DEFAULTS underlie both. The CLI only ever writes the local overlay, so
your comments in config.yaml survive.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

LOCAL_FILE = "smartremote.local.yaml"

DEFAULTS = {
    "poll_interval_seconds": 2,
    # gpu:none jobs run in parallel up to this; gpu:required always serialize.
    "max_parallel_cpu_jobs": 3,
    "hermes": {
        "enabled": False,
        "base_url": "http://127.0.0.1:8642",  # Hermes Agent gateway default port
        "send_path": "/send",
        "token": "",
    },
    "models": {
        "local": {"backend": "ollama", "base_url": "http://127.0.0.1:11434"},
        "remote": {
            "providers": {
                "claude-code": {"kind": "cli", "command": "claude"},
                "codex": {"kind": "cli", "command": "codex"},
            }
        },
        # Cline CLI as an agentic local executor (drives an Ollama model in the workspace).
        "cline": {"command": "cline", "args": ["-y", "--auto-approve", "true"]},
        # Who does what. provider is "local" (Ollama), "cline" (agentic local), or a remote id.
        "roles": {
            "planner": {"provider": "remote", "model": "claude-code"},
            "executor": {"provider": "local", "model": "qwen3-coder:32b"},
            "guard": {"provider": "remote", "model": "claude-code"},
            "escalation": {"provider": "remote", "model": "codex"},
        },
    },
}

ROLE_HELP = {
    "planner": "writes the most efficient plan (remote frontier agent)",
    "executor": "applies the plan locally (Ollama model)",
    "guard": "checks the executor's work against the plan",
    "escalation": "takes over when the local model struggles; can propose a new local model",
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read_yaml(p: Path) -> dict:
    if p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {}


def load_config(path: str | Path | None = None) -> dict:
    """Load config.yaml (at `path`) overlaid with the sibling smartremote.local.yaml.

    `path` is <root>/config.yaml. If None, returns built-in DEFAULTS.
    """
    cfg = copy.deepcopy(DEFAULTS)
    if path is None:
        return cfg
    path = Path(path)
    cfg = _deep_merge(cfg, _read_yaml(path))
    cfg = _deep_merge(cfg, _read_yaml(path.parent / LOCAL_FILE))
    return cfg


def update_local(root: str | Path, patch: dict) -> dict:
    """Deep-merge `patch` into <root>/smartremote.local.yaml (the CLI-managed overlay)."""
    p = Path(root) / LOCAL_FILE
    merged = _deep_merge(_read_yaml(p), patch)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(
        "# Managed by the `smartremote` CLI (models/hermes). Edits here may be overwritten.\n"
        + yaml.safe_dump(merged, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(tmp, p)
    return merged
