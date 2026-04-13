"""RefineValidator — three-layer modify+delete enforcement (STG-04, STG-05).

Validator is the AUTHORITATIVE post-validation gate. Per RESEARCH.md
Pitfall #1, schema Literal["modify","delete"] prevents op="add" but does
NOT prevent op="modify" referencing a phantom note_id; only this module's
ID cross-reference closes that gap.

Decision references (see .planning/phases/02-refine-service-and-pipeline-integration/02-CONTEXT.md):
  * D-13 — ghost-note velocity-floor threshold via Settings.refine_ghost_velocity_max
  * D-14 — piano range [21, 108]
  * D-15 — duplicate target_note_id rejects entire edit list

Returns a 2-tuple (applied, rejected). The caller (RefineService, Plan 03)
decides whether to raise RefineValidationError based on the rejected list.
"""
from __future__ import annotations

from typing import Protocol

from shared.contracts import (
    ExpressiveNote,
    HumanizedPerformance,
    PianoScore,
    RefineEditOp,
    ScoreNote,
)

from backend.services.refine_prompt import ID_PATTERN, _derive_note_id_map

PIANO_LOW_MIDI = 21   # A0 — D-14 lower bound inclusive
PIANO_HIGH_MIDI = 108  # C8 — D-14 upper bound inclusive


class _SettingsLike(Protocol):
    """Duck-typed Settings surface the validator reads."""
    refine_ghost_velocity_max: int


class RefineValidationError(Exception):
    """Raised by RefineService (Plan 03) when the validator rejects every edit.

    Not raised by the validator itself — the validator returns tuples; the
    service decides on the failure policy (skip-on-failure per INT-03).
    """


class RefineValidator:
    """Validates LLM-emitted RefineEditOps against a source performance.

    Three-layer enforcement per STG-04:
      1. Schema (Phase 1, in contracts.py): Literal["modify","delete"] prevents op="add".
      2. Prompt (D-09, backend/services/refine_prompt.py): SYSTEM_PROMPT forbids addition.
      3. Post-validation (HERE): ID cross-reference + ghost guard + pitch-range + duplicate guard.
    """

    def __init__(self, settings: _SettingsLike) -> None:
        self.settings = settings

    def validate(
        self,
        source: HumanizedPerformance | PianoScore,
        edits: list[RefineEditOp],
    ) -> tuple[list[RefineEditOp], list[tuple[RefineEditOp, str]]]:
        """Partition edits into applied and rejected.

        Returns
        -------
        (applied, rejected):
            applied: edits that passed every gate, in original order
            rejected: list of (edit, reason) — reason is a short snake_case string
        """
        # D-15: short-circuit on duplicate target_note_id. Reject ENTIRE list.
        seen: set[str] = set()
        duplicate_found = False
        for e in edits:
            if e.target_note_id in seen:
                duplicate_found = True
                break
            seen.add(e.target_note_id)
        if duplicate_found:
            return ([], [(e, "duplicate_target_note_id") for e in edits])

        note_id_map = _derive_note_id_map(source)

        applied: list[RefineEditOp] = []
        rejected: list[tuple[RefineEditOp, str]] = []

        for edit in edits:
            reason = self._reject_reason(edit, note_id_map)
            if reason is None:
                applied.append(edit)
            else:
                rejected.append((edit, reason))

        return (applied, rejected)

    def _reject_reason(
        self,
        edit: RefineEditOp,
        note_id_map: dict[str, ExpressiveNote | ScoreNote],
    ) -> str | None:
        """Return a snake_case rejection reason, or None if the edit passes."""
        # Gate 1: shape check on target_note_id.
        if ID_PATTERN.match(edit.target_note_id) is None:
            return "malformed_target_note_id"

        # Gate 2: cross-reference against source note IDs.
        source_note = note_id_map.get(edit.target_note_id)
        if source_note is None:
            return "unknown_target_note_id"

        # Gate 3 (D-13): ghost-note guard on harmony_correction.
        if (
            edit.rationale == "harmony_correction"
            and source_note.velocity <= self.settings.refine_ghost_velocity_max
        ):
            return "ghost_harmony_correction"

        # Gate 4 (D-14): pitch-range guard for modify edits that set pitch.
        if (
            edit.op == "modify"
            and edit.pitch is not None
            and (edit.pitch < PIANO_LOW_MIDI or edit.pitch > PIANO_HIGH_MIDI)
        ):
            return "pitch_out_of_range"

        return None
