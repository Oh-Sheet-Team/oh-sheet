"""Tests for GET /v1/capabilities (Phase 3, D-22).

The endpoint tells the frontend whether enable_refine=true submissions
have any chance of succeeding. Returns a single boolean: true when the
backend has an Anthropic key configured, false otherwise. Does NOT reveal
the key itself, its length, model, or prompt version.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.config import settings


def test_capabilities_refine_available_true_when_key_set(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-22 happy path: key configured -> refine_available=true."""
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("sk-ant-test-key-not-real"))
    response = client.get("/v1/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body == {"refine_available": True}


def test_capabilities_refine_available_false_when_key_unset(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-22: no key -> refine_available=false (frontend disables checkbox)."""
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    response = client.get("/v1/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body == {"refine_available": False}


def test_capabilities_response_has_exactly_one_field(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defense against scope creep: the endpoint must not leak additional fields."""
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("sk-ant-test-key-not-real"))
    response = client.get("/v1/capabilities")
    body = response.json()
    assert set(body.keys()) == {"refine_available"}


def test_capabilities_requires_no_auth(client: TestClient) -> None:
    """D-22: project has no auth layer. Endpoint must respond to anonymous GET."""
    response = client.get("/v1/capabilities")
    assert response.status_code == 200
