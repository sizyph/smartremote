"""Test safety net: force mock model providers for every test (and any run_job
subprocess they spawn), so the suite never makes real Claude/Ollama calls.

test_provider_resolution opts out locally via monkeypatch.delenv to verify the
real provider wiring.
"""
import pytest


@pytest.fixture(autouse=True)
def _force_mock_llm(monkeypatch):
    monkeypatch.setenv("SMARTREMOTE_FAKE_LLM", "1")
