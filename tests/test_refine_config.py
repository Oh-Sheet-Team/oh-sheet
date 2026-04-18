"""Sanity checks on the refine-stage settings surface."""
from __future__ import annotations

from backend.config import Settings


def test_refine_defaults_no_key(monkeypatch) -> None:
    # No API key → refine_active auto-derives to False.
    monkeypatch.delenv("OHSHEET_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OHSHEET_REFINE_ENABLED", raising=False)
    s = Settings(_env_file=None)
    assert s.refine_enabled is None
    assert s.refine_active is False
    assert s.refine_model == "claude-sonnet-4-6"
    assert s.refine_max_searches == 5
    assert s.refine_budget_sec == 300
    assert s.refine_call_timeout_sec == 120
    assert s.anthropic_api_key is None


def test_refine_auto_enabled_with_key(monkeypatch) -> None:
    # Key present + no explicit override → refine_active auto-derives to True.
    monkeypatch.setenv("OHSHEET_ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.delenv("OHSHEET_REFINE_ENABLED", raising=False)
    s = Settings(_env_file=None)
    assert s.refine_enabled is None
    assert s.refine_active is True


def test_refine_force_disabled_with_key(monkeypatch) -> None:
    # Explicit override can force-disable even when key is present.
    monkeypatch.setenv("OHSHEET_ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setenv("OHSHEET_REFINE_ENABLED", "false")
    s = Settings(_env_file=None)
    assert s.refine_enabled is False
    assert s.refine_active is False


def test_refine_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("OHSHEET_REFINE_ENABLED", "false")
    monkeypatch.setenv("OHSHEET_REFINE_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.setenv("OHSHEET_REFINE_MAX_SEARCHES", "3")
    monkeypatch.setenv("OHSHEET_REFINE_BUDGET_SEC", "600")
    monkeypatch.setenv("OHSHEET_REFINE_CALL_TIMEOUT_SEC", "90")
    monkeypatch.setenv("OHSHEET_ANTHROPIC_API_KEY", "sk-test-key")
    s = Settings()
    assert s.refine_enabled is False
    assert s.refine_active is False
    assert s.refine_model == "claude-haiku-4-5-20251001"
    assert s.refine_max_searches == 3
    assert s.refine_budget_sec == 600
    assert s.refine_call_timeout_sec == 90
    assert s.anthropic_api_key == "sk-test-key"
