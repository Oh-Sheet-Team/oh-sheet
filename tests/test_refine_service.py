"""Unit tests for RefineService — uses a fake Anthropic client.

The fake client mimics AsyncAnthropic.messages.create() just enough to
drive the service through its success, cache, and fallback paths without
touching the network.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from shared.contracts import (
    ExpressionMap,
    HumanizedPerformance,
    PianoScore,
    QualitySignal,
    ScoreMetadata,
    ScoreNote,
    TempoMapEntry,
)
from shared.storage.local import LocalBlobStore

from backend.config import settings
from backend.services.refine import RefineService


def _score() -> PianoScore:
    return PianoScore(
        right_hand=[
            ScoreNote(id="rh-1", pitch=72, onset_beat=0.0, duration_beat=1.0, velocity=80, voice=1),
        ],
        left_hand=[
            ScoreNote(id="lh-1", pitch=48, onset_beat=0.0, duration_beat=2.0, velocity=70, voice=1),
        ],
        metadata=ScoreMetadata(
            key="C:major",
            time_signature=(4, 4),
            tempo_map=[TempoMapEntry(time_sec=0.0, beat=0.0, bpm=100.0)],
            difficulty="intermediate",
        ),
    )


def _humanized(score: PianoScore) -> HumanizedPerformance:
    return HumanizedPerformance(
        expressive_notes=[],
        expression=ExpressionMap(),
        score=score,
        quality=QualitySignal(overall_confidence=0.9, warnings=[]),
    )


class _FakeToolUseBlock:
    def __init__(self, name: str, input_: dict[str, Any]) -> None:
        self.type = "tool_use"
        self.name = name
        self.input = input_


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, content: list[Any]) -> None:
        self.content = content


class _FakeMessages:
    def __init__(self, outputs: list[Any]) -> None:
        self._outputs = list(outputs)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        out = self._outputs.pop(0)
        if isinstance(out, BaseException):
            raise out
        if callable(out):
            return await out() if asyncio.iscoroutinefunction(out) else out()
        return out


class _FakeAnthropic:
    def __init__(self, outputs: list[Any]) -> None:
        self.messages = _FakeMessages(outputs)


@pytest.fixture
def blob(tmp_path):
    return LocalBlobStore(tmp_path / "blob")


@pytest.mark.asyncio
async def test_success_merges_refinements_into_score(blob):
    refinements = {
        "title": "Test Song",
        "composer": "Test Composer",
        "tempo_marking": "Andante",
        "key_signature": "Db:major",
        "time_signature": [4, 4],
        "tempo_bpm": 66,
        "staff_split_hint": 60,
        "sections": [
            {"start_beat": 0.0, "end_beat": 16.0, "label": "intro", "custom_label": "Opening"},
        ],
        "repeats": [
            {"start_beat": 0.0, "end_beat": 16.0, "kind": "simple"},
        ],
    }
    fake = _FakeAnthropic([
        _FakeResponse([_FakeToolUseBlock("submit_refinements", refinements)]),
    ])
    svc = RefineService(blob_store=blob, client=fake)
    result = await svc.run(_score(), title_hint="test", artist_hint=None)
    assert isinstance(result, PianoScore)
    md = result.metadata
    assert md.title == "Test Song"
    assert md.composer == "Test Composer"
    assert md.tempo_marking == "Andante"
    assert md.key == "Db:major"
    assert md.time_signature == (4, 4)
    assert md.tempo_map[0].bpm == pytest.approx(66.0)
    assert md.staff_split_hint == 60
    assert len(md.sections) == 1
    assert md.sections[0].custom_label == "Opening"
    assert len(md.repeats) == 1


@pytest.mark.asyncio
async def test_success_preserves_notes(blob):
    fake = _FakeAnthropic([
        _FakeResponse([_FakeToolUseBlock("submit_refinements", {"title": "X"})]),
    ])
    svc = RefineService(blob_store=blob, client=fake)
    original = _score()
    result = await svc.run(original, title_hint=None, artist_hint=None)
    assert [n.pitch for n in result.right_hand] == [n.pitch for n in original.right_hand]
    assert [n.pitch for n in result.left_hand] == [n.pitch for n in original.left_hand]


@pytest.mark.asyncio
async def test_humanized_performance_roundtrip(blob):
    fake = _FakeAnthropic([
        _FakeResponse([_FakeToolUseBlock("submit_refinements", {"title": "X", "composer": "Y"})]),
    ])
    svc = RefineService(blob_store=blob, client=fake)
    perf = _humanized(_score())
    result = await svc.run(perf, title_hint=None, artist_hint=None)
    assert isinstance(result, HumanizedPerformance)
    assert result.score.metadata.title == "X"
    assert result.score.metadata.composer == "Y"


@pytest.mark.asyncio
async def test_llm_failure_passes_input_through_with_warning(blob):
    fake = _FakeAnthropic([
        RuntimeError("network melted"),
    ])
    svc = RefineService(blob_store=blob, client=fake)
    perf = _humanized(_score())
    result = await svc.run(perf, title_hint=None, artist_hint=None)
    assert isinstance(result, HumanizedPerformance)
    # Notes unchanged
    assert result.score.metadata.title is None
    # Warning attached
    assert any("refine" in w for w in result.quality.warnings)


@pytest.mark.asyncio
async def test_missing_submit_refinements_falls_back(blob):
    fake = _FakeAnthropic([
        _FakeResponse([_FakeTextBlock("I could not find the song.")]),
    ])
    svc = RefineService(blob_store=blob, client=fake)
    perf = _humanized(_score())
    result = await svc.run(perf, title_hint=None, artist_hint=None)
    assert result.score.metadata.title is None
    assert any("refine" in w for w in result.quality.warnings)


@pytest.mark.asyncio
async def test_cache_hit_skips_llm(blob):
    # First call: write to cache.
    fake1 = _FakeAnthropic([
        _FakeResponse([_FakeToolUseBlock("submit_refinements", {"title": "Cached"})]),
    ])
    svc1 = RefineService(blob_store=blob, client=fake1)
    result1 = await svc1.run(_score(), title_hint=None, artist_hint=None)
    assert result1.metadata.title == "Cached"
    assert len(fake1.messages.calls) == 1

    # Second call with a client whose create() would fail — should not be called.
    fake2 = _FakeAnthropic([RuntimeError("should not be called")])
    svc2 = RefineService(blob_store=blob, client=fake2)
    result2 = await svc2.run(_score(), title_hint=None, artist_hint=None)
    assert result2.metadata.title == "Cached"
    assert len(fake2.messages.calls) == 0


@pytest.mark.asyncio
async def test_budget_exceeded_falls_back(blob, monkeypatch):
    async def _slow() -> Any:
        await asyncio.sleep(10)
        return _FakeResponse([_FakeToolUseBlock("submit_refinements", {"title": "late"})])

    fake = _FakeAnthropic([_slow])
    svc = RefineService(blob_store=blob, client=fake)
    monkeypatch.setattr(settings, "refine_budget_sec", 0.05)
    perf = _humanized(_score())
    result = await svc.run(perf, title_hint=None, artist_hint=None)
    assert result.score.metadata.title is None
    assert any("budget" in w.lower() or "refine" in w for w in result.quality.warnings)


@pytest.mark.asyncio
async def test_invalid_section_label_falls_through_to_other(blob):
    refinements = {
        "sections": [
            {"start_beat": 0.0, "end_beat": 4.0, "label": "not_a_real_label", "custom_label": "Weird"},
            {"start_beat": 4.0, "end_beat": 8.0, "label": "verse"},
        ],
    }
    fake = _FakeAnthropic([
        _FakeResponse([_FakeToolUseBlock("submit_refinements", refinements)]),
    ])
    svc = RefineService(blob_store=blob, client=fake)
    result = await svc.run(_score(), title_hint=None, artist_hint=None)
    assert len(result.metadata.sections) == 2
    assert result.metadata.sections[0].label.value == "other"
    assert result.metadata.sections[1].label.value == "verse"


@pytest.mark.asyncio
async def test_invalid_repeat_kind_is_dropped(blob):
    refinements = {
        "repeats": [
            {"start_beat": 0.0, "end_beat": 8.0, "kind": "da_capo"},   # unsupported
            {"start_beat": 8.0, "end_beat": 16.0, "kind": "simple"},
        ],
    }
    fake = _FakeAnthropic([
        _FakeResponse([_FakeToolUseBlock("submit_refinements", refinements)]),
    ])
    svc = RefineService(blob_store=blob, client=fake)
    result = await svc.run(_score(), title_hint=None, artist_hint=None)
    assert [r.kind for r in result.metadata.repeats] == ["simple"]
