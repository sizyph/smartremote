"""Model scout: benchmark local (Ollama) models on a small eval suite, rank them,
and decide whether a challenger should replace the current champion (the executor).

  quality = fraction of eval tasks passed
  speed   = decode tok/s (from Ollama timing fields)
  fit     = ran fully on the GPU

A challenger is eligible only if it fits the GPU and clears the speed floor, and is
promoted only if it beats the champion's quality by a margin. Tasks are
answer-checkable (no execution of model output) — extend EVAL_TASKS with your own,
including a sandboxed code runner, for sharper signal.

Offline/testable: with SMARTREMOTE_FAKE_LLM=1, benchmark_model() returns
deterministic fake results keyed by tag, so ranking/promotion logic is testable.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .providers import OllamaProvider, ProviderError

SPEED_FLOOR_TOKS = float(os.environ.get("SMARTREMOTE_SPEED_FLOOR", "15"))  # "not too slow"
PROMOTE_MARGIN = float(os.environ.get("SMARTREMOTE_PROMOTE_MARGIN", "0.05"))  # +5% quality


@dataclass
class Task:
    id: str
    prompt: str
    expect: list[str]  # pass if any expected substring appears (case-insensitive)


# Safe, answer-checkable tasks (no execution of model output).
EVAL_TASKS = [
    Task("arith", "What is 17 * 23? Reply with only the number.", ["391"]),
    Task("syllogism", "All Bloops are Razzies. All Razzies are Lazzies. Are all Bloops Lazzies? yes or no.", ["yes"]),
    Task("py-slice", "In Python, what does sum([1,2,3][1:]) evaluate to? Reply with only the number.", ["5"]),
    Task("py-len", "In Python, what is len('hello'.replace('l','')) ? Reply with only the number.", ["3"]),
    Task("reverse", "Reverse the string 'abcde'. Reply with only the result.", ["edcba"]),
    Task("json", 'Given JSON {"a":{"b":7}}, what is the value at a.b? Reply with only the number.', ["7"]),
]

# Deterministic fake scores (quality, tok/s) for SMARTREMOTE_FAKE_LLM runs.
_FAKE = {
    "qwen3-coder:32b": (1.0, 45.0),
    "devstral:24b": (0.83, 60.0),
    "qwen3:30b-a3b": (0.83, 150.0),
    "deepseek-r1:32b": (0.83, 40.0),
    "qwen3:14b": (0.66, 90.0),
}


@dataclass
class BenchResult:
    tag: str
    passed: int
    total: int
    tok_s: float | None = None
    fits_gpu: bool | None = None
    error: str | None = None

    @property
    def quality(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def eligible(self) -> bool:
        if self.error or self.fits_gpu is False:
            return False
        return not (self.tok_s is not None and self.tok_s < SPEED_FLOOR_TOKS)


def benchmark_model(tag: str, base_url: str = "http://127.0.0.1:11434", tasks=None) -> BenchResult:
    tasks = tasks or EVAL_TASKS
    if os.environ.get("SMARTREMOTE_FAKE_LLM"):
        q, tk = _FAKE.get(tag, (0.5, 30.0))
        return BenchResult(tag, round(q * len(tasks)), len(tasks), tk, True)
    provider = OllamaProvider(tag, base_url)
    passed, toks = 0, []
    for t in tasks:
        try:
            resp = provider.generate(t.prompt)
        except ProviderError as e:
            return BenchResult(tag, passed, len(tasks), None, None, str(e))
        answer = resp.get("response", "")
        if any(s.lower() in answer.lower() for s in t.expect):
            passed += 1
        ec, ed = resp.get("eval_count"), resp.get("eval_duration")
        if ec and ed:
            toks.append(ec / (ed / 1e9))
    return BenchResult(tag, passed, len(tasks),
                       sum(toks) / len(toks) if toks else None, _fits_gpu(tag))


def _fits_gpu(tag: str) -> bool | None:
    """True if `ollama ps` shows the model running fully on GPU (best-effort)."""
    import shutil
    import subprocess

    if not shutil.which("ollama"):
        return None
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10).stdout
    except Exception:  # noqa: BLE001
        return None
    base = tag.split(":")[0]
    for line in out.splitlines()[1:]:
        parts = line.split()
        if parts and parts[0].split(":")[0] == base:
            return "GPU" in line and "CPU" not in line  # "100% GPU"
    return None


def rank(results: list[BenchResult]) -> list[BenchResult]:
    return sorted(results, key=lambda r: (r.eligible, r.quality, r.tok_s or 0.0), reverse=True)


def choose_winner(champion_tag: str, results: list[BenchResult], margin: float = PROMOTE_MARGIN) -> str | None:
    by_tag = {r.tag: r for r in results}
    champ = by_tag.get(champion_tag)
    champ_q = champ.quality if champ else -1.0
    challengers = [r for r in results if r.tag != champion_tag and r.eligible]
    if not challengers:
        return None
    best = max(challengers, key=lambda r: (r.quality, r.tok_s or 0.0))
    return best.tag if best.quality >= champ_q + margin else None


def report_table(results: list[BenchResult], champion: str | None = None) -> str:
    lines = ["| model | quality | tok/s | fits GPU | eligible |", "|---|---|---|---|---|"]
    for r in rank(results):
        star = " (champion)" if r.tag == champion else ""
        tok = f"{r.tok_s:.0f}" if r.tok_s is not None else "?"
        fits = {True: "yes", False: "no", None: "?"}[r.fits_gpu]
        note = f" — {r.error}" if r.error else ""
        lines.append(f"| {r.tag}{star} | {r.passed}/{r.total} | {tok} | {fits} | {'yes' if r.eligible else 'no'}{note} |")
    return "\n".join(lines)
