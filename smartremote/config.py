"""Load <root>/config.yaml, falling back to built-in defaults."""
from __future__ import annotations

from pathlib import Path

import yaml

DEFAULTS = {
    "poll_interval_seconds": 2,
    # gpu:none jobs run in parallel up to this many; gpu:required always serialize.
    "max_parallel_cpu_jobs": 3,
    "hermes": {"enabled": False, "base_url": "", "token": ""},
}


def load_config(path: str | Path | None) -> dict:
    cfg = {**DEFAULTS, "hermes": dict(DEFAULTS["hermes"])}
    if path and Path(path).exists():
        loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        hermes = {**cfg["hermes"], **(loaded.pop("hermes", {}) or {})}
        cfg.update(loaded)
        cfg["hermes"] = hermes
    return cfg
