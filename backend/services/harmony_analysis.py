"""Beat-synchronous chordal harmony analysis over transcribed note events.

This module complements :mod:`backend.services.chord_recognition`:

* ``chord_recognition`` listens to the waveform and produces coarse
  beat-level chord labels when librosa is available.
* ``harmony_analysis`` works on the *symbolic* note stream emitted by the
  transcription stage, refines those labels against the actual notes we
  plan to arrange, and enriches the result with inversion and Roman-numeral
  metadata.

The design intentionally mirrors the "root / quality / bass" decomposition
from modern chord-recognition pipelines without introducing a heavyweight
model dependency:

1. Build beat-synchronous spans from the tempo map, optionally inserting
   audio-guide boundaries from ``recognize_chords`` when available.
2. Aggregate pitch-class energy from the transcribed note events inside
   each span, weighting bass/chord tracks more heavily than melody.
3. Score a constrained vocabulary of chord templates against that symbolic
   pitch-class profile.
4. Reuse the existing key-aware HMM Viterbi smoother from
   ``chord_recognition`` so the symbolic pass prefers musically coherent
   progressions over one-beat flicker.
5. Derive inversion (slash bass) from the lowest stable active note and
   Roman numerals via music21 when available.

The output still fits the existing ``HarmonicAnalysis.chords`` contract,
so downstream arrange / engrave code does not need a second harmony path.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from backend.contracts import (
    InstrumentRole,
    RealtimeChordEvent,
    TempoMapEntry,
    beat_to_sec,
    sec_to_beat,
)
from backend.services.chord_recognition import (
    _PITCH_NAMES,
    _smooth_chords_hmm,
)
from backend.services.transcription_cleanup import NoteEvent

log = logging.getLogger(__name__)

DEFAULT_HARMONY_MIN_CONFIDENCE = 0.45
DEFAULT_HARMONY_MIN_SPAN_SEC = 0.08
DEFAULT_HARMONY_GUIDE_MATCH_BONUS = 0.10
DEFAULT_HARMONY_GUIDE_ROOT_BONUS = 0.05
DEFAULT_HARMONY_GUIDE_BASS_BONUS = 0.03
DEFAULT_HARMONY_NON_CHORD_PENALTY = 0.18
DEFAULT_HARMONY_ESSENTIAL_TONE_PENALTY = 0.05

_ROLE_WEIGHTS: dict[InstrumentRole, float] = {
    InstrumentRole.BASS: 1.30,
    InstrumentRole.CHORDS: 1.00,
    InstrumentRole.PIANO: 0.95,
    InstrumentRole.MELODY: 0.35,
    InstrumentRole.OTHER: 0.20,
}

_QUALITY_INTERVALS: tuple[tuple[str, tuple[int, ...], tuple[float, ...]], ...] = (
    ("maj", (0, 4, 7), (1.00, 0.95, 0.80)),
    ("min", (0, 3, 7), (1.00, 0.95, 0.80)),
    ("dim", (0, 3, 6), (1.00, 0.92, 0.78)),
    ("aug", (0, 4, 8), (1.00, 0.92, 0.78)),
    ("sus2", (0, 2, 7), (1.00, 0.88, 0.78)),
    ("sus4", (0, 5, 7), (1.00, 0.88, 0.78)),
    ("7", (0, 4, 7, 10), (1.00, 0.95, 0.80, 0.70)),
    ("maj7", (0, 4, 7, 11), (1.00, 0.95, 0.80, 0.72)),
    ("min7", (0, 3, 7, 10), (1.00, 0.95, 0.80, 0.72)),
    ("hdim7", (0, 3, 6, 10), (1.00, 0.92, 0.78, 0.68)),
    ("dim7", (0, 3, 6, 9), (1.00, 0.92, 0.78, 0.68)),
)


@dataclass(frozen=True)
class _HarmonyTemplate:
    label: str
    root: int
    quality: str
    pitch_classes: frozenset[int]
    essential_tones: frozenset[int]


@dataclass(frozen=True)
class _GuideChord:
    root: int
    quality: str
    bass: int | None
    label: str
    start_sec: float
    end_sec: float


@dataclass
class _SpanEvidence:
    start_sec: float
    end_sec: float
    profile: Any
    total_weight: float
    distinct_pitch_classes: set[int]
    bass_pc: int | None
    guide: _GuideChord | None

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec

    @property
    def has_symbolic_content(self) -> bool:
        return self.total_weight > 0.0 and len(self.distinct_pitch_classes) >= 2


@dataclass
class HarmonyAnalysisStats:
    """Per-run summary of the symbolic harmony pass."""

    detected_count: int = 0
    no_chord_count: int = 0
    unique_labels: int = 0
    inversion_count: int = 0
    roman_numeral_count: int = 0
    guided_spans: int = 0
    audio_fallback_spans: int = 0
    skipped: bool = False
    warnings: list[str] = field(default_factory=list)

    def as_warnings(self) -> list[str]:
        if self.skipped:
            reason = self.warnings[0] if self.warnings else "no harmonic material"
            return [f"harmony analysis skipped ({reason})"]

        out: list[str] = []
        if self.detected_count:
            extras: list[str] = []
            if self.inversion_count:
                extras.append(f"{self.inversion_count} inversions")
            if self.roman_numeral_count:
                extras.append(f"{self.roman_numeral_count} roman numerals")
            if self.audio_fallback_spans:
                extras.append(f"{self.audio_fallback_spans} audio-guided")
            suffix = f" [{', '.join(extras)}]" if extras else ""
            out.append(
                f"harmony: {self.detected_count} spans "
                f"({self.unique_labels} unique labels){suffix}"
            )
        elif self.no_chord_count:
            out.append("harmony: no spans above symbolic score threshold")

        out.extend(self.warnings)
        return out


def format_chord_progression(
    chords: list[RealtimeChordEvent],
    *,
    max_items: int | None = 12,
) -> str:
    """Return a compact progression string for terminal logs.

    ``max_items`` limits how many chords appear in the string; ``None``
    means include every chord (for small tests or non-terminal consumers).
    """
    if not chords:
        return "none"

    slice_end = None if max_items is None else max_items
    parts: list[str] = []
    for chord in chords[:slice_end]:
        time_tag = f"{chord.time_sec:.2f}s"
        roman = f" ({chord.roman_numeral})" if chord.roman_numeral else ""
        parts.append(f"{time_tag} {chord.label}{roman}")

    if max_items is not None and len(chords) > max_items:
        parts.append(f"... (+{len(chords) - max_items} more)")
    return " -> ".join(parts)


def chord_progression_dump_text(
    chords: list[RealtimeChordEvent],
    *,
    key: str,
    job_id: str | None,
) -> str:
    """Multiline chord listing for debug files (one chord per row)."""
    lines = [
        "# chord progression",
        f"job_id: {job_id or '—'}",
        f"key: {key}",
        f"chord_count: {len(chords)}",
        "",
    ]
    if not chords:
        lines.append("(no chords)")
    else:
        for chord in chords:
            roman = f"\troman={chord.roman_numeral}" if chord.roman_numeral else ""
            bass = f"\tbass_pc={chord.bass}" if chord.bass is not None else ""
            lines.append(
                f"{chord.time_sec:.4f}s\t{chord.duration_sec:.4f}s\t{chord.label}"
                f"\tconf={chord.confidence:.3f}{roman}{bass}"
            )
    return "\n".join(lines) + "\n"


def _build_symbolic_templates() -> tuple[Any, list[_HarmonyTemplate]]:
    import numpy as np  # noqa: PLC0415

    rows: list[Any] = []
    metas: list[_HarmonyTemplate] = []
    for root in range(12):
        for quality, intervals, weights in _QUALITY_INTERVALS:
            row = np.zeros(12, dtype=np.float32)
            pcs = tuple((root + interval) % 12 for interval in intervals)
            for pc, weight in zip(pcs, weights):
                row[pc] = float(weight)
            norm = float(np.linalg.norm(row))
            if norm > 0.0:
                row = row / norm
            rows.append(row)
            label = f"{_PITCH_NAMES[root]}:{quality}"
            metas.append(
                _HarmonyTemplate(
                    label=label,
                    root=root,
                    quality=quality,
                    pitch_classes=frozenset(pcs),
                    essential_tones=frozenset(pcs[:2]),
                )
            )
    return np.stack(rows), metas


def _merge_boundaries(boundaries: list[float]) -> list[float]:
    if not boundaries:
        return []

    merged: list[float] = []
    for value in sorted(float(v) for v in boundaries if math.isfinite(float(v))):
        if not merged or abs(value - merged[-1]) > 1e-3:
            merged.append(value)
        else:
            merged[-1] = min(merged[-1], value)
    return merged


def _parse_chord_label(
    label: str,
    *,
    start_sec: float = 0.0,
    end_sec: float = 0.0,
) -> _GuideChord | None:
    if not label or label == "N":
        return None

    base = label
    bass_name: str | None = None
    if "/" in label:
        base, bass_name = label.split("/", 1)

    if ":" in base:
        root_name, quality = base.split(":", 1)
    else:
        root_name, quality = base, "maj"

    if root_name not in _PITCH_NAMES:
        return None

    bass_pc: int | None = None
    if bass_name is not None:
        bass_name = bass_name.strip()
        if bass_name in _PITCH_NAMES:
            bass_pc = _PITCH_NAMES.index(bass_name)

    return _GuideChord(
        root=_PITCH_NAMES.index(root_name),
        quality=quality.strip(),
        bass=bass_pc,
        label=label,
        start_sec=float(start_sec),
        end_sec=float(end_sec),
    )


def _roman_numeral_for_chord(
    *,
    root: int,
    quality: str,
    bass: int | None,
    key_label: str,
) -> str | None:
    guide = _parse_chord_label(f"{_PITCH_NAMES[root]}:{quality}")
    if guide is None:
        return None

    parts = key_label.split(":")
    if len(parts) != 2 or parts[0] not in _PITCH_NAMES:
        return None

    try:
        from music21 import chord as m21_chord  # noqa: PLC0415
        from music21 import key as m21_key  # noqa: PLC0415
        from music21 import roman  # noqa: PLC0415
    except ImportError:
        return None

    mode = parts[1].lower()
    if mode not in {"major", "minor"}:
        return None

    try:
        key_obj = m21_key.Key(parts[0], mode)
        template = next(
            intervals for quality_name, intervals, _weights in _QUALITY_INTERVALS
            if quality_name == quality
        )
    except (StopIteration, Exception):
        return None

    chord_pcs = [((root + interval) % 12) for interval in template]
    note_names = [
        f"{_PITCH_NAMES[chord_pcs[0]]}4",
        *[f"{_PITCH_NAMES[pc]}5" for pc in chord_pcs[1:]],
    ]
    if bass is not None and bass in chord_pcs and bass != root:
        note_names.insert(0, f"{_PITCH_NAMES[bass]}3")

    try:
        rn = roman.romanNumeralFromChord(m21_chord.Chord(note_names), key_obj)
    except Exception:  # noqa: BLE001 — music21 raises on exotic spellings
        return None
    figure = getattr(rn, "figure", None)
    return str(figure) if figure else None


def _enrich_audio_guide(
    guide_chords: list[RealtimeChordEvent],
    *,
    key_label: str,
) -> list[RealtimeChordEvent]:
    enriched: list[RealtimeChordEvent] = []
    for event in guide_chords:
        parsed = _parse_chord_label(
            event.label,
            start_sec=event.time_sec,
            end_sec=event.time_sec + event.duration_sec,
        )
        quality = parsed.quality if parsed is not None else None
        bass = parsed.bass if parsed is not None else None
        roman_numeral = None
        if parsed is not None:
            roman_numeral = _roman_numeral_for_chord(
                root=parsed.root,
                quality=parsed.quality,
                bass=parsed.bass,
                key_label=key_label,
            )
        enriched.append(
            event.model_copy(
                update={
                    "quality": quality,
                    "bass": bass,
                    "roman_numeral": roman_numeral,
                    "source": "audio",
                }
            )
        )
    return enriched


def _guide_for_span(
    start_sec: float,
    end_sec: float,
    guides: list[_GuideChord],
) -> _GuideChord | None:
    best: _GuideChord | None = None
    best_overlap = 0.0
    for guide in guides:
        overlap = max(
            0.0,
            min(end_sec, guide.end_sec) - max(start_sec, guide.start_sec),
        )
        if overlap > best_overlap:
            best = guide
            best_overlap = overlap
    return best


def _beat_boundaries(
    tempo_map: list[TempoMapEntry],
    max_time_sec: float,
) -> list[float]:
    if max_time_sec <= 0.0:
        return [0.0]

    max_beat = max(1, int(math.ceil(sec_to_beat(max_time_sec, tempo_map))))
    boundaries: list[float] = [0.0]
    for beat in range(1, max_beat + 1):
        time_sec = float(beat_to_sec(float(beat), tempo_map))
        if DEFAULT_HARMONY_MIN_SPAN_SEC < time_sec < max_time_sec - DEFAULT_HARMONY_MIN_SPAN_SEC:
            boundaries.append(time_sec)
    boundaries.append(float(max_time_sec))
    return boundaries


def _span_profile(
    events_by_role: dict[InstrumentRole, list[NoteEvent]],
    start_sec: float,
    end_sec: float,
    guide: _GuideChord | None,
) -> _SpanEvidence:
    import numpy as np  # noqa: PLC0415

    profile = np.zeros(12, dtype=np.float32)
    duration = max(end_sec - start_sec, 1e-6)
    total_weight = 0.0
    pitch_classes: set[int] = set()
    bass_candidates: list[tuple[int, float]] = []

    for role, events in events_by_role.items():
        role_weight = _ROLE_WEIGHTS.get(role, 0.5)
        bass_role_bonus = 0.35 if role == InstrumentRole.BASS else 0.0
        for onset, offset, pitch, amp, _bends in events:
            overlap = max(0.0, min(end_sec, float(offset)) - max(start_sec, float(onset)))
            if overlap <= 0.0:
                continue

            pitch = int(pitch)
            amp = max(float(amp), 0.05)
            pc = pitch % 12
            weight = (overlap / duration) * amp * role_weight
            profile[pc] += weight
            total_weight += weight
            pitch_classes.add(pc)
            bass_candidates.append((pitch, overlap * amp * (role_weight + bass_role_bonus)))

    bass_pc: int | None = None
    if bass_candidates:
        strongest = max(score for _pitch, score in bass_candidates)
        stable = [pitch for pitch, score in bass_candidates if score >= strongest * 0.6]
        if stable:
            bass_pc = min(stable) % 12
        else:
            bass_pc = min(pitch for pitch, _score in bass_candidates) % 12

    return _SpanEvidence(
        start_sec=start_sec,
        end_sec=end_sec,
        profile=profile,
        total_weight=total_weight,
        distinct_pitch_classes=pitch_classes,
        bass_pc=bass_pc,
        guide=guide,
    )


def _score_evidence_against_templates(
    evidence: _SpanEvidence,
    templates: Any,
    metas: list[_HarmonyTemplate],
) -> Any:
    import numpy as np  # noqa: PLC0415

    scores = np.full(len(metas), 1e-6, dtype=np.float32)
    if evidence.total_weight > 0.0:
        norm = float(np.linalg.norm(evidence.profile))
        normalized = evidence.profile / max(norm, 1e-9)
    else:
        normalized = evidence.profile

    guide = evidence.guide
    for idx, meta in enumerate(metas):
        score = float(templates[idx] @ normalized) if evidence.total_weight > 0.0 else 0.0

        if evidence.total_weight > 0.0:
            non_chord_weight = sum(
                float(evidence.profile[pc]) for pc in range(12)
                if pc not in meta.pitch_classes
            )
            non_chord_share = non_chord_weight / max(evidence.total_weight, 1e-9)
            score -= DEFAULT_HARMONY_NON_CHORD_PENALTY * non_chord_share

            missing_essentials = sum(
                1 for pc in meta.essential_tones
                if float(evidence.profile[pc]) <= 1e-6
            )
            score -= DEFAULT_HARMONY_ESSENTIAL_TONE_PENALTY * missing_essentials

            score += 0.05 * float(evidence.profile[meta.root] / max(evidence.total_weight, 1e-9))
            if evidence.bass_pc is not None:
                if evidence.bass_pc == meta.root:
                    score += 0.06
                elif evidence.bass_pc in meta.pitch_classes:
                    score += 0.03

        if guide is not None:
            if meta.root == guide.root and meta.quality == guide.quality:
                score += DEFAULT_HARMONY_GUIDE_MATCH_BONUS
            elif meta.root == guide.root:
                score += DEFAULT_HARMONY_GUIDE_ROOT_BONUS

            if (
                evidence.bass_pc is not None
                and guide.bass is not None
                and evidence.bass_pc == guide.bass
                and evidence.bass_pc in meta.pitch_classes
            ):
                score += DEFAULT_HARMONY_GUIDE_BASS_BONUS

        if not evidence.has_symbolic_content and guide is not None:
            if meta.root == guide.root and meta.quality == guide.quality:
                score = max(score, 0.72)
            elif meta.root == guide.root:
                score = max(score, 0.55)

        scores[idx] = float(min(max(score, 1e-6), 1.0))

    return scores


def analyze_chordal_harmony(
    events_by_role: dict[InstrumentRole, list[NoteEvent]],
    *,
    tempo_map: list[TempoMapEntry] | None = None,
    key_label: str = "C:major",
    guide_chords: list[RealtimeChordEvent] | None = None,
    hmm_enabled: bool = True,
    hmm_self_transition: float = 0.8,
    hmm_temperature: float = 1.0,
    min_confidence: float = DEFAULT_HARMONY_MIN_CONFIDENCE,
) -> tuple[list[RealtimeChordEvent], HarmonyAnalysisStats]:
    """Return a refined chord stream from the symbolic note events.

    ``guide_chords`` is optional audio-derived chord output from
    :func:`backend.services.chord_recognition.recognize_chords`. When
    present, it contributes boundary hints and acts as a soft prior, but the
    final labels are still resolved against the symbolic note stream.
    """
    stats = HarmonyAnalysisStats()
    active_events = {
        role: list(events)
        for role, events in events_by_role.items()
        if events and role != InstrumentRole.OTHER
    }

    parsed_guides = [
        parsed for event in (guide_chords or [])
        if (
            parsed := _parse_chord_label(
                event.label,
                start_sec=event.time_sec,
                end_sec=event.time_sec + event.duration_sec,
            )
        ) is not None
    ]

    if not active_events:
        if guide_chords:
            enriched = _enrich_audio_guide(guide_chords, key_label=key_label)
            stats.detected_count = len(enriched)
            stats.unique_labels = len({event.label for event in enriched})
            stats.audio_fallback_spans = len(enriched)
            stats.roman_numeral_count = sum(1 for event in enriched if event.roman_numeral)
            stats.inversion_count = sum(1 for event in enriched if event.bass is not None)
            return enriched, stats

        stats.skipped = True
        stats.warnings.append("no symbolic note events")
        return [], stats

    if tempo_map:
        effective_tempo_map = list(tempo_map)
    else:
        effective_tempo_map = [TempoMapEntry(time_sec=0.0, beat=0.0, bpm=120.0)]

    max_time_sec = max(float(event[1]) for events in active_events.values() for event in events)
    if max_time_sec <= 0.0:
        stats.skipped = True
        stats.warnings.append("non-positive note durations")
        return [], stats

    boundaries = _beat_boundaries(effective_tempo_map, max_time_sec)
    for guide in parsed_guides:
        boundaries.extend([guide.start_sec, guide.end_sec])
    boundaries = _merge_boundaries(boundaries)

    spans: list[_SpanEvidence] = []
    for start_sec, end_sec in zip(boundaries, boundaries[1:]):
        if end_sec - start_sec < DEFAULT_HARMONY_MIN_SPAN_SEC:
            continue
        guide = _guide_for_span(start_sec, end_sec, parsed_guides)
        if guide is not None:
            stats.guided_spans += 1
        spans.append(_span_profile(active_events, start_sec, end_sec, guide))

    if not spans:
        if guide_chords:
            enriched = _enrich_audio_guide(guide_chords, key_label=key_label)
            stats.detected_count = len(enriched)
            stats.unique_labels = len({event.label for event in enriched})
            stats.audio_fallback_spans = len(enriched)
            return enriched, stats

        stats.skipped = True
        stats.warnings.append("no usable harmonic spans")
        return [], stats

    templates, metas = _build_symbolic_templates()
    roots = [meta.root for meta in metas]
    labels = [meta.label for meta in metas]

    import numpy as np  # noqa: PLC0415

    emission_scores = np.stack([
        _score_evidence_against_templates(span, templates, metas) for span in spans
    ], axis=1)

    if hmm_enabled:
        try:
            best_indices = _smooth_chords_hmm(
                emission_scores,
                labels,
                roots,
                key_label=key_label,
                self_transition=hmm_self_transition,
                temperature=hmm_temperature,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("symbolic harmony HMM failed, falling back to argmax: %s", exc)
            stats.warnings.append(f"harmony smoothing failed: {exc}")
            best_indices = np.argmax(emission_scores, axis=0).tolist()
    else:
        best_indices = np.argmax(emission_scores, axis=0).tolist()

    raw_events: list[RealtimeChordEvent] = []
    for span_idx, template_idx in enumerate(best_indices):
        span = spans[span_idx]
        template = metas[int(template_idx)]
        selected_score = float(emission_scores[int(template_idx), span_idx])
        guide = span.guide

        if selected_score < min_confidence and guide is None:
            stats.no_chord_count += 1
            continue

        bass_pc: int | None = None
        if span.bass_pc is not None and span.bass_pc in template.pitch_classes and span.bass_pc != template.root:
            bass_pc = span.bass_pc
        elif guide is not None and guide.root == template.root and guide.quality == template.quality:
            if guide.bass is not None and guide.bass in template.pitch_classes and guide.bass != template.root:
                bass_pc = guide.bass

        label = template.label
        if bass_pc is not None:
            label = f"{label}/{_PITCH_NAMES[bass_pc]}"

        if guide is not None and not span.has_symbolic_content:
            source = "audio"
            selected_score = max(selected_score, 0.72)
            stats.audio_fallback_spans += 1
        elif guide is not None and guide.root == template.root and guide.quality == template.quality:
            source = "hybrid"
        else:
            source = "symbolic"

        roman_numeral = _roman_numeral_for_chord(
            root=template.root,
            quality=template.quality,
            bass=bass_pc,
            key_label=key_label,
        )

        raw_events.append(
            RealtimeChordEvent(
                time_sec=span.start_sec,
                duration_sec=span.duration_sec,
                label=label,
                root=template.root,
                confidence=round(min(max(selected_score, 0.0), 1.0), 3),
                quality=template.quality,
                bass=bass_pc,
                roman_numeral=roman_numeral,
                source=source,
            )
        )

    if not raw_events:
        if guide_chords:
            enriched = _enrich_audio_guide(guide_chords, key_label=key_label)
            stats.detected_count = len(enriched)
            stats.unique_labels = len({event.label for event in enriched})
            stats.audio_fallback_spans = len(enriched)
            stats.roman_numeral_count = sum(1 for event in enriched if event.roman_numeral)
            stats.inversion_count = sum(1 for event in enriched if event.bass is not None)
            return enriched, stats
        return [], stats

    collapsed: list[RealtimeChordEvent] = []
    for event in raw_events:
        if (
            collapsed
            and collapsed[-1].label == event.label
            and collapsed[-1].root == event.root
            and collapsed[-1].bass == event.bass
        ):
            previous = collapsed[-1]
            collapsed[-1] = previous.model_copy(
                update={
                    "duration_sec": previous.duration_sec + event.duration_sec,
                    "confidence": max(previous.confidence, event.confidence),
                    "roman_numeral": previous.roman_numeral or event.roman_numeral,
                    "source": (
                        previous.source if previous.source == event.source else "hybrid"
                    ),
                }
            )
        else:
            collapsed.append(event)

    stats.detected_count = len(collapsed)
    stats.unique_labels = len({event.label for event in collapsed})
    stats.inversion_count = sum(1 for event in collapsed if event.bass is not None)
    stats.roman_numeral_count = sum(1 for event in collapsed if event.roman_numeral)
    return collapsed, stats
