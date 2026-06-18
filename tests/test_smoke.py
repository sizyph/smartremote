"""Smoke tests: the contract, the park/resume cycle, and scheduler invariants."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from smartremote import models
from smartremote import state as st
from smartremote.config import load_config, update_local
from smartremote.dispatcher import Dispatcher
from smartremote.job import JobError, parse_job
from smartremote.selftest import run_selftest


def test_park_resume_selftest():
    # Drives ingest -> park-on-question -> answer -> resume -> done; asserts inside.
    run_selftest()


def test_job_validation():
    good = parse_job("---\nid: x\ntype: build\nagent: local\ngpu: none\n---\n# Goal\nhi\n")
    assert good.id == "x" and good.gpu == "none"
    with pytest.raises(JobError):
        parse_job("no frontmatter at all")
    with pytest.raises(JobError):
        parse_job("---\nid: x\ntype: bogus\nagent: local\ngpu: none\n---\n# g\nx\n")


def _mk(tmp: Path, jid: str, gpu: str, deps=None):
    (tmp / "inbox" / f"{jid}.md").write_text(
        f"---\nid: {jid}\ntype: build\nagent: local\ngpu: {gpu}\n"
        f"depends_on: {deps or []}\n"
        f"notify: {{on_done: none, on_question: none, on_fail: none}}\n---\n# Goal\nx\n",
        encoding="utf-8",
    )


def test_scheduler_invariants():
    tmp = Path(tempfile.mkdtemp(prefix="sr-test-"))
    try:
        disp = Dispatcher(tmp, load_config(None))  # max_parallel_cpu_jobs = 3
        for n in (1, 2):
            _mk(tmp, f"gpu{n}", "required")
        for n in (1, 2, 3, 4):
            _mk(tmp, f"cpu{n}", "none")
        _mk(tmp, "dep1", "none", deps=["gpu1"])

        disp.ingest()
        disp.schedule()  # inspect launch decisions before reaping
        launched = set(disp.running)
        gpu = {j for j in launched if j.startswith("gpu")}
        cpu = {j for j in launched if j.startswith("cpu")}

        assert len(gpu) == 1, f"GPU must serialize to 1, got {gpu}"
        assert disp.gpu.holder() in gpu, "GPU lock not held by the launched gpu job"
        assert len(cpu) == 3, f"CPU must cap at max_parallel=3, got {cpu}"
        assert st.Status(tmp / "jobs" / "dep1").read()["state"] == "blocked"
    finally:
        for p in disp.running.values():
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def test_config_overlay(tmp_path):
    # config.yaml (human) + smartremote.local.yaml (CLI) + DEFAULTS, deep-merged.
    (tmp_path / "config.yaml").write_text("max_parallel_cpu_jobs: 5\n", encoding="utf-8")
    update_local(tmp_path, {"models": {"roles": {"executor": {"provider": "local", "model": "devstral:24b"}}}})
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg["max_parallel_cpu_jobs"] == 5  # from config.yaml
    assert cfg["models"]["roles"]["executor"]["model"] == "devstral:24b"  # from overlay
    assert cfg["models"]["roles"]["planner"]["provider"] == "remote"  # from DEFAULTS
    assert models.role_model(cfg, "executor") == ("local", "devstral:24b")


def test_recommended_models_fit_24gb():
    assert models.RECOMMENDED
    for r in models.RECOMMENDED:
        assert r.vram_q4_gb < 24, f"{r.tag} won't fit 24 GB"
        assert r.role in {"planner", "executor", "guard", "escalation"}


def test_provider_resolution(monkeypatch):
    from smartremote import providers

    cfg = load_config(None)
    monkeypatch.delenv("SMARTREMOTE_FAKE_LLM", raising=False)
    assert isinstance(providers.provider_for_role(cfg, "executor"), providers.OllamaProvider)
    assert isinstance(providers.provider_for_role(cfg, "planner"), providers.RemoteCliProvider)
    monkeypatch.setenv("SMARTREMOTE_FAKE_LLM", "1")
    assert isinstance(providers.provider_for_role(cfg, "planner"), providers.MockProvider)


def test_parse_verdict():
    from smartremote.providers import parse_verdict

    assert parse_verdict('{"ok": true, "issues": [], "summary": "good"}')["ok"] is True
    assert parse_verdict('noise {"ok": false, "issues": ["x"]} tail')["ok"] is False
    assert parse_verdict("not json")["ok"] is True  # lenient default avoids false escalation


def _pipeline_ctx(tmp_path):
    from smartremote.runners import RunContext

    job = parse_job("---\nid: p\ntype: build\nagent: cloud\ngpu: none\nneeds_human: false\n---\n# Goal\nbuild X\n")
    return RunContext(job=job, job_dir=tmp_path, cfg=load_config(None))


def test_pipeline_executes_and_guards(tmp_path, monkeypatch):
    monkeypatch.setenv("SMARTREMOTE_FAKE_LLM", "1")
    from smartremote.runners.pipeline import PlanExecuteRunner

    out = PlanExecuteRunner().run(_pipeline_ctx(tmp_path))
    assert (tmp_path / "artifacts" / "plan.md").exists()
    assert (tmp_path / "artifacts" / "result.md").exists()
    assert "artifacts/result.escalated.md" not in out.artifacts
    assert "ok" in out.summary


def test_pipeline_escalates_on_guard_fail(tmp_path, monkeypatch):
    monkeypatch.setenv("SMARTREMOTE_FAKE_LLM", "1")
    monkeypatch.setenv("SMARTREMOTE_FAKE_GUARD", "fail")
    from smartremote.runners.pipeline import PlanExecuteRunner

    out = PlanExecuteRunner().run(_pipeline_ctx(tmp_path))
    assert (tmp_path / "artifacts" / "result.escalated.md").exists()
    assert "escalated" in out.summary


def test_scout_ranking_and_winner():
    from smartremote import scout

    results = [scout.benchmark_model(t) for t in ("qwen3:14b", "qwen3-coder:32b", "devstral:24b")]
    # fake quality: qwen3-coder 1.0 > devstral 0.83 > qwen3:14b 0.66
    assert [r.tag for r in scout.rank(results)][0] == "qwen3-coder:32b"
    # weak champion gets beaten; strong champion is retained
    assert scout.choose_winner("qwen3:14b", results) == "qwen3-coder:32b"
    assert scout.choose_winner("qwen3-coder:32b", results) is None


def test_scout_runner_promotes_on_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("SMARTREMOTE_FAKE_LLM", "1")
    from smartremote.runners import RunContext
    from smartremote.runners.scout import ScoutRunner

    job_dir = tmp_path / "jobs" / "scout"
    job_dir.mkdir(parents=True)
    (job_dir / "answers").mkdir()
    (job_dir / "answers" / "promote-model.txt").write_text("approve", encoding="utf-8")  # pre-answer the park

    cfg = load_config(None)
    cfg["models"]["roles"]["executor"]["model"] = "qwen3:14b"  # weak champion
    job = parse_job(
        "---\nid: s\ntype: pipeline\nrunner: scout\nagent: local\ngpu: required\n---\n"
        "# Goal\nscout\n## Challengers\n- qwen3-coder:32b\n- devstral:24b\n")
    out = ScoutRunner().run(RunContext(job=job, job_dir=job_dir, cfg=cfg))

    assert "promoted executor" in out.summary
    promoted = load_config(tmp_path / "config.yaml")["models"]["roles"]["executor"]["model"]
    assert promoted == "qwen3-coder:32b"
