"""V5 — D-02 fixture regression guard.

After the SCHEMA_VERSION bump to 3.1.0, the 14 committed fixtures at
tests/fixtures/scores/*.json must:
  1. Stay tagged schema_version="3.0.0" (guard against accidental regeneration).
  2. Still validate via Pydantic (proves the `schema_version: str` field was
     NOT tightened to `Literal[...]` — old payloads stay parseable).
  3. Round-trip byte-equal through model_dump(mode="json") (guards against
     silent field-shape drift in any Phase 1 contract edit).

Parametrized over FIXTURE_NAMES so individual failures name the broken fixture.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fixtures import FIXTURE_NAMES, load_score_fixture

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scores"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_3_0_0_fixture_schema_version_preserved(name: str) -> None:
    """D-02: committed fixtures must stay at schema_version='3.0.0'."""
    raw = json.loads((_FIXTURES_DIR / f"{name}.json").read_text())
    assert raw["schema_version"] == "3.0.0", (
        f"fixture {name} lost its 3.0.0 tag — per D-02, fixtures must NOT be "
        "regenerated after the SCHEMA_VERSION bump. "
        "Run `git checkout tests/fixtures/scores/` to restore."
    )


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_3_0_0_fixture_still_validates_against_3_1_0_contracts(name: str) -> None:
    """Loose `schema_version: str` field keeps old payloads parseable after bump."""
    fixture = load_score_fixture(name)  # re-validates via Pydantic — raises on drift
    assert fixture.schema_version == "3.0.0", (
        f"fixture {name}: Pydantic validated but schema_version changed — "
        "something mutated the loader path"
    )


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_3_0_0_fixture_roundtrips_byte_equal(name: str) -> None:
    """model_validate -> model_dump must produce the same JSON (schema shape integrity)."""
    raw = json.loads((_FIXTURES_DIR / f"{name}.json").read_text())
    fixture = load_score_fixture(name)
    dumped = fixture.model_dump(mode="json")
    assert dumped == raw, (
        f"fixture {name}: round-trip altered the payload shape — "
        "a Phase 1 contract change broke backward compatibility with 3.0.0 payloads. "
        "If you see 'dropped/added' keys, a contract field was removed or made required; "
        "if you see 'type-coerced' values (e.g. int->float), the field's type changed."
    )
