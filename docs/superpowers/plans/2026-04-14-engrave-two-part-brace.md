# Engrave Two-Part Braced Grand Staff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch `engrave` from emitting a single `<part>` with `<staves>2</staves>` (music21 `PartStaff`) to emitting two `<part>` elements joined by a `<part-group>` with `<group-symbol>brace</group-symbol>`, so `musicxml2ly` / LilyPond renders a proper grand staff with bass clef on the left-hand staff.

**Architecture:** One-file change inside `backend/services/engrave.py`. Replace two `music21.stream.PartStaff` objects with two `music21.stream.Part` objects wrapped by the same `music21.layout.StaffGroup(symbol="brace")`. Two sanitizer helpers (`_remap_voices_per_staff`, `_align_tie_chain_voices`) are updated to match the new shape. No contract or pipeline change.

**Tech Stack:** Python 3.10+, music21 9.9.1, pytest, LilyPond (via `musicxml2ly`).

**Spec:** [`docs/superpowers/specs/2026-04-14-engrave-two-part-brace-design.md`](../specs/2026-04-14-engrave-two-part-brace-design.md)

---

## File Structure

**Modify:**
- `backend/services/engrave.py` — swap `PartStaff` → `Part`; remove per-part `partName`/`partAbbreviation`; scope tie-chain tracking per-part.
- `tests/test_engrave_quality.py` — rewrite the three grand-staff structure tests to expect two-part encoding.

**No new files.** No contract changes. No pipeline or config changes.

---

## Task 1: Rewrite grand-staff structure tests to expect two-part encoding (TDD — red)

**Files:**
- Modify: `tests/test_engrave_quality.py` — the `_count_staff` helper (line ~345), `test_l2_grand_staff_single_part` (line ~359), `test_l2_rh_only_fixture_still_single_part` (line ~440).

We rewrite the existing tests first so they express the new contract: two `<part>` elements, a `<part-group>` with `<group-symbol>brace</group-symbol>`, treble clef on part 1, bass clef on part 2, no `<staves>` element anywhere. Against the current production code these will fail (red).

- [ ] **Step 1: Replace the `_count_staff` helper with `_count_part_notes`**

Find the current helper (around line 345):

```python
def _count_staff(musicxml: bytes, staff: int) -> int:
    """Count pitched ``<note>`` elements tagged with ``<staff>{staff}</staff>``."""
    from lxml import etree

    count = 0
    for note in etree.fromstring(musicxml).iter("note"):
        if note.find("rest") is not None:
            continue
        staff_elem = note.find("staff")
        if staff_elem is not None and int(staff_elem.text) == staff:
            count += 1
    return count
```

Replace with:

```python
def _count_part_notes(musicxml: bytes, part_index: int) -> int:
    """Count pitched ``<note>`` elements in the N-th ``<part>`` (0-based)."""
    from lxml import etree

    parts = etree.fromstring(musicxml).findall("part")
    if part_index >= len(parts):
        return 0
    count = 0
    for note in parts[part_index].iter("note"):
        if note.find("rest") is not None:
            continue
        count += 1
    return count
```

- [ ] **Step 2: Rewrite `test_l2_grand_staff_single_part` as `test_l2_grand_staff_two_parts_braced`**

Find the current test (around line 359) and replace its body with:

```python
def test_l2_grand_staff_two_parts_braced(engraved_artifacts):
    """Piano scores render as two ``<part>`` elements joined by a brace group.

    We emit MusicXML in the "two parts + part-group(brace)" idiom instead
    of the "one part + <staves>2" idiom. Rationale: ``musicxml2ly`` (the
    MusicXML → LilyPond bridge) does not reliably honor the one-part /
    multi-staff encoding, so LilyPond renders both staves with a treble
    clef and left-hand notes end up as ledger-line stacks below the
    staff. Two-part + brace is handled correctly by LilyPond, MuseScore,
    Verovio, and OSMD.
    """
    from lxml import etree

    # two_hand_chordal is the canonical grand-staff fixture: 12 RH notes
    # (triads) and 8 LH notes (octaves).
    musicxml, _ = engraved_artifacts["two_hand_chordal"]
    root = etree.fromstring(musicxml)

    parts = root.findall("part")
    assert len(parts) == 2, f"expected two parts (RH + LH), got {len(parts)}"

    # No <staves> element under any part — that's the old one-part idiom.
    assert not list(root.iter("staves")), (
        "unexpected <staves> element — two-part encoding should not declare it"
    )

    # part-list carries a brace-group wrapping both score-parts.
    part_list = root.find("part-list")
    assert part_list is not None
    groups = part_list.findall("part-group")
    assert groups, "expected a <part-group> in <part-list>"
    brace_starts = [
        g for g in groups
        if g.get("type") == "start" and g.findtext("group-symbol") == "brace"
    ]
    assert brace_starts, "expected a brace-type part-group in part-list"
    assert brace_starts[0].findtext("group-name") == "Piano"

    # Clef sanity: part 1 = treble (G on line 2), part 2 = bass (F on line 4).
    def clef_of(part_elem) -> tuple[str, str]:
        clef = part_elem.find("measure/attributes/clef")
        assert clef is not None
        return (clef.findtext("sign") or "", clef.findtext("line") or "")

    assert clef_of(parts[0]) == ("G", "2"), f"RH clef: {clef_of(parts[0])}"
    assert clef_of(parts[1]) == ("F", "4"), f"LH clef: {clef_of(parts[1])}"

    # 12 RH notes on part 1, 8 LH notes on part 2 (same counts as before).
    assert _count_part_notes(musicxml, 0) == 12
    assert _count_part_notes(musicxml, 1) == 8
```

- [ ] **Step 3: Rewrite `test_l2_rh_only_fixture_still_single_part` as `test_l2_rh_only_fixture_still_braced`**

Find the current test (around line 440) and replace:

```python
def test_l2_rh_only_fixture_still_braced(engraved_artifacts):
    """An empty-LH fixture still emits a two-part braced grand staff.

    The LH ``<part>`` will contain measures with only rests, but the
    ``<part-group>`` (brace) must still be present so renderers draw a
    grand staff with the expected shape.
    """
    from lxml import etree

    musicxml, _ = engraved_artifacts["empty_left_hand"]
    root = etree.fromstring(musicxml)

    parts = root.findall("part")
    assert len(parts) == 2, f"expected two parts even with empty LH, got {len(parts)}"

    brace_starts = [
        g for g in root.findall("part-list/part-group")
        if g.get("type") == "start" and g.findtext("group-symbol") == "brace"
    ]
    assert brace_starts, "expected brace part-group even when LH is empty"

    # LH part exists but has no pitched notes.
    assert _count_part_notes(musicxml, 1) == 0
```

- [ ] **Step 4: Commit the failing tests**

```bash
git add tests/test_engrave_quality.py
git commit -m "test(engrave): expect two-part braced MusicXML structure"
```

These tests will fail until Task 4 lands. Committing them first keeps the TDD chain auditable in git history.

---

## Task 2: Confirm the new tests fail against the current implementation

**Files:** none (verification step).

- [ ] **Step 1: Run the rewritten tests and confirm they fail**

Run:

```bash
pytest tests/test_engrave_quality.py::test_l2_grand_staff_two_parts_braced \
       tests/test_engrave_quality.py::test_l2_rh_only_fixture_still_braced -v
```

Expected: both FAIL.

- `test_l2_grand_staff_two_parts_braced` should fail on `assert len(parts) == 2, f"expected two parts ..., got 1"` because the current code emits one merged `<part>` with `<staves>2</staves>`.
- `test_l2_rh_only_fixture_still_braced` should fail on the same assertion.

Record the failure message (for the commit body in Task 8). Do not proceed if either test passes — that means the assertions don't actually match the current encoding and the test isn't validating what we think.

---

## Task 3: Add a regression test for the Bob Marley failure mode

**Files:**
- Modify: `tests/test_engrave_quality.py` — add one new test alongside the rewritten ones.

The failure was observed on job `f255d56b4243` (YouTube `oFRbZJXjWIA`): RH pitches C4–E6, LH pitches E2–B3, LilyPond collapsed both staves to treble clef. We pin a tight regression with a minimal fixture.

- [ ] **Step 1: Write the failing regression test**

Add to `tests/test_engrave_quality.py` (below the grand-staff tests, around line 460):

```python
def test_l2_bass_range_lh_renders_on_bass_clef_part():
    """Regression for job f255d56b4243 (YouTube oFRbZJXjWIA).

    LH pitches in the E2–B3 range must land on a part with a bass
    clef, not on a part that inherits a treble clef. Before the
    two-part / brace fix, music21's PartStaff encoding passed through
    musicxml2ly as a single staff group with a dropped bass clef, and
    LilyPond drew all LH notes as ledger-line stacks below the treble.
    """
    import xml.etree.ElementTree as etree

    from backend.contracts import (
        PianoScore,
        ScoreMetadata,
        ScoreNote,
        TempoMapEntry,
    )
    from backend.services.engrave import _engrave_sync

    # Minimal reproduction: four RH quarters in the C4–E6 range and four
    # LH quarters in the E2–B3 range, one measure of 4/4.
    rh = [
        ScoreNote(id=f"rh-{i}", pitch=p, onset_beat=float(i), duration_beat=1.0, velocity=75, voice=1)
        for i, p in enumerate([62, 67, 72, 76])  # D4, G4, C5, E5
    ]
    lh = [
        ScoreNote(id=f"lh-{i}", pitch=p, onset_beat=float(i), duration_beat=1.0, velocity=75, voice=1)
        for i, p in enumerate([40, 47, 54, 59])  # E2, B2, F#3, B3
    ]
    score = PianoScore(
        right_hand=rh,
        left_hand=lh,
        metadata=ScoreMetadata(
            key="B:minor",
            time_signature=(4, 4),
            tempo_map=[TempoMapEntry(time_sec=0.0, beat=0.0, bpm=136.0)],
        ),
    )

    _pdf, musicxml, _midi, _chords = _engrave_sync(score, title="bob", composer="")
    root = etree.fromstring(musicxml)

    parts = root.findall("part")
    assert len(parts) == 2, f"expected two parts, got {len(parts)}"

    # RH part → treble (G/2); LH part → bass (F/4).
    rh_clef = parts[0].find("measure/attributes/clef")
    lh_clef = parts[1].find("measure/attributes/clef")
    assert rh_clef is not None and rh_clef.findtext("sign") == "G"
    assert lh_clef is not None and lh_clef.findtext("sign") == "F"

    # Every LH note lives on the LH part only.
    lh_pitches_in_rh = [
        int(n.findtext("pitch/octave")) for n in parts[0].iter("note")
        if n.find("pitch") is not None and int(n.findtext("pitch/octave")) <= 3
    ]
    assert not lh_pitches_in_rh, (
        f"LH-range pitches ended up on the RH part: {lh_pitches_in_rh}"
    )
```

- [ ] **Step 2: Run the regression test — expect failure**

```bash
pytest tests/test_engrave_quality.py::test_l2_bass_range_lh_renders_on_bass_clef_part -v
```

Expected: FAIL on `assert len(parts) == 2` (current code emits one merged part).

- [ ] **Step 3: Commit the failing regression test**

```bash
git add tests/test_engrave_quality.py
git commit -m "test(engrave): regression for bass-range LH clef collapse"
```

---

## Task 4: Swap `PartStaff` → `Part` in `_render_musicxml_bytes` (green)

**Files:**
- Modify: `backend/services/engrave.py:504-664`.

The core change. Replace two `PartStaff` objects (one merged `<part>` with `<staves>2</staves>`) with two `Part` objects (two separate `<part>` elements, braced by `StaffGroup`). Also remove per-part `partName`/`partAbbreviation` so only the `StaffGroup`'s `name="Piano"` carries the label.

- [ ] **Step 1: Update the encoding comment**

Find lines 504–511 in `backend/services/engrave.py`:

```python
    # Render as a real piano grand staff: two ``PartStaff`` objects bound
    # by a braced ``StaffGroup``. music21 emits this as a single
    # ``<part>`` with ``<staves>2</staves>`` and staff-tagged notes —
    # exactly what OSMD / LilyPond / MuseScore expect for piano. Previous
    # behavior emitted two separate ``<part>``s ("Right Hand", "Left
    # Hand") which renderers drew as two stacked instruments without a
    # connecting brace. Both PartStaffs share ``partName="Piano"`` so the
    # merged ``<score-part>`` gets the correct "Piano" label.
```

Replace with:

```python
    # Render as a real piano grand staff: two ``Part`` objects bound by a
    # braced ``StaffGroup``. music21 emits this as two separate
    # ``<part>`` elements joined in ``<part-list>`` by a ``<part-group>``
    # with ``<group-symbol>brace</group-symbol>`` — the canonical
    # MusicXML grand-staff idiom that ``musicxml2ly`` / LilyPond, OSMD,
    # MuseScore, and Verovio all render identically. The older
    # ``PartStaff`` path emitted one merged ``<part>`` with
    # ``<staves>2</staves>`` and per-note ``<staff>`` tags, which
    # ``musicxml2ly`` mishandled: the LH clef was dropped and both staves
    # rendered in treble. The ``StaffGroup`` name "Piano" sits on the
    # brace; the individual ``<part>`` elements have empty
    # ``<part-name/>`` tags, so renderers show a single "Piano" label.
```

- [ ] **Step 2: Swap the two `PartStaff` instantiations for `Part`**

Find lines 512–519 of `backend/services/engrave.py`:

```python
    piano_parts: list = []
    for hand_name, notes, clef in (
        ("Right Hand", score.right_hand, music21.clef.TrebleClef()),
        ("Left Hand", score.left_hand, music21.clef.BassClef()),
    ):
        part = music21.stream.PartStaff()
        part.partName = "Piano"
        part.partAbbreviation = "Pno."
```

Replace with:

```python
    piano_parts: list = []
    for hand_name, notes, clef, part_id in (
        ("Right Hand", score.right_hand, music21.clef.TrebleClef(), "P-RH"),
        ("Left Hand", score.left_hand, music21.clef.BassClef(), "P-LH"),
    ):
        part = music21.stream.Part(id=part_id)
        # Intentionally no partName / partAbbreviation. The StaffGroup
        # owns the "Piano" / "Pno." label; per-part names would render
        # twice (once per staff) in some tools.
```

- [ ] **Step 3: Keep the `StaffGroup` wiring (no change — but verify)**

The `StaffGroup` registration at lines 650–664 already passes `piano_parts` (both parts) with `symbol="brace"`. No edit needed — verify the block still reads:

```python
    # Bind the two Parts into a braced grand staff.
    s.insert(
        0,
        music21.layout.StaffGroup(
            piano_parts,
            name="Piano",
            abbreviation="Pno.",
            symbol="brace",
            barTogether=True,
        ),
    )
```

(Optional: update the preceding comment block describing the legacy `<staves>2</staves>` behavior — see next step.)

- [ ] **Step 4: Update the `StaffGroup` comment to match the new encoding**

Find lines 650–654:

```python
    # Bind the two PartStaffs into a braced grand staff. music21 detects
    # the StaffGroup and collapses them into one ``<part>`` with
    # ``<staves>2</staves>`` in the MusicXML output, with each note
    # carrying a ``<staff>`` tag so renderers place it on the correct
    # stave.
```

Replace with:

```python
    # Bind the two Parts into a braced grand staff. music21 emits this
    # as a ``<part-group type="start"><group-symbol>brace</group-symbol>
    # </part-group>`` wrapper in ``<part-list>``, followed by two
    # ``<part>`` elements — one for RH, one for LH. No ``<staves>`` tag,
    # no per-note ``<staff>`` tag; clef lives in each part's own
    # measure-1 ``<attributes>`` block.
```

- [ ] **Step 5: Run the structure tests — expect pass**

```bash
pytest tests/test_engrave_quality.py::test_l2_grand_staff_two_parts_braced \
       tests/test_engrave_quality.py::test_l2_rh_only_fixture_still_braced \
       tests/test_engrave_quality.py::test_l2_bass_range_lh_renders_on_bass_clef_part -v
```

Expected: all three PASS.

If any test fails, inspect the emitted MusicXML with:

```bash
python -c "
from backend.services.engrave import _engrave_sync
from tests.fixtures import load_score_fixture
_, xml, _, _ = _engrave_sync(load_score_fixture('two_hand_chordal'), title='x', composer='')
print(xml.decode()[:2000])
"
```

to debug what the new encoding actually looks like.

---

## Task 5: Scope tie-chain tracking per-part in `_align_tie_chain_voices`

**Files:**
- Modify: `backend/services/engrave.py:785-835`.

In the old encoding, `(step, octave, alter, staff)` uniquely identified a tied pitch across the entire MusicXML. In the new encoding `<staff>` tags are absent, so `staff` is always `"1"` — a tie-start on the RH part could be "matched" against a same-pitch tie-stop on the LH part. That's a cross-hand collision we need to prevent. Fix by resetting the `open_ties` dict at each new `<part>`.

- [ ] **Step 1: Write a failing test for cross-hand tie isolation**

Add to `tests/test_engrave_quality.py` (after the existing tie-related tests, around line 520):

```python
def test_l2_tie_chain_per_part_isolation():
    """Open ties don't leak across parts.

    In the two-part encoding, the same pitch can appear (untied) on both
    RH and LH. The tie-chain sanitizer must track open ties per-part so
    an RH tie-start never "matches" an LH non-tied attack of the same
    pitch.
    """
    import xml.etree.ElementTree as etree

    from backend.contracts import (
        PianoScore,
        ScoreMetadata,
        ScoreNote,
        TempoMapEntry,
    )
    from backend.services.engrave import _engrave_sync

    # RH has a tied C4 crossing a bar line; LH has an untied C4 in
    # measure 2. The tie sanitizer must not rewrite the LH note's voice.
    rh = [
        ScoreNote(id="rh-0", pitch=60, onset_beat=0.0, duration_beat=8.0, velocity=75, voice=1),
    ]
    lh = [
        ScoreNote(id="lh-0", pitch=60, onset_beat=5.0, duration_beat=1.0, velocity=75, voice=1),
    ]
    score = PianoScore(
        right_hand=rh,
        left_hand=lh,
        metadata=ScoreMetadata(
            key="C:major",
            time_signature=(4, 4),
            tempo_map=[TempoMapEntry(time_sec=0.0, beat=0.0, bpm=120.0)],
        ),
    )

    _pdf, musicxml, _midi, _chords = _engrave_sync(score, title="x", composer="")
    root = etree.fromstring(musicxml)
    parts = root.findall("part")
    assert len(parts) == 2

    # Every tied note pair must have both ends within the same <part>.
    for part in parts:
        open_pitches: dict[tuple[str, str, str], bool] = {}
        for note in part.iter("note"):
            pitch = note.find("pitch")
            if pitch is None:
                continue
            key = (
                pitch.findtext("step") or "",
                pitch.findtext("octave") or "",
                pitch.findtext("alter") or "0",
            )
            for tie in note.findall("tie"):
                typ = tie.get("type")
                if typ == "start":
                    open_pitches[key] = True
                elif typ == "stop":
                    # stop must match a start in the SAME part.
                    assert open_pitches.get(key), (
                        f"tie-stop with no matching tie-start in same part for pitch {key}"
                    )
                    open_pitches[key] = False
```

- [ ] **Step 2: Run the new test — verify it exercises the codepath**

```bash
pytest tests/test_engrave_quality.py::test_l2_tie_chain_per_part_isolation -v
```

Expected: the test probably PASSES against the current Task-4 state (cross-hand collisions only trigger when RH and LH share a pitch at the exact bar boundary — uncommon). We still want the test so the scoping change below is defended by a real assertion.

If it fails, inspect the emitted MusicXML to understand why — the `open_ties` leak could have caused a spurious voice rewrite on the LH note.

- [ ] **Step 3: Scope `open_ties` per `<part>`**

Find `_align_tie_chain_voices` in `backend/services/engrave.py` (around line 785). The current body has `open_ties` initialized **once** before the outer loop; move it **inside** the outer part loop and update the docstring.

Current (around lines 797–826):

```python
    parser = ET.XMLParser()
    root = ET.fromstring(raw, parser=parser)

    open_ties: dict[tuple[str, str, str, str], str] = {}
    rewrites = 0
    for part in root.findall("part"):
        for measure in part.findall("measure"):
            for note in measure.findall("note"):
                pitch = note.find("pitch")
                if pitch is None:
                    continue
                key = (
                    pitch.findtext("step") or "",
                    pitch.findtext("octave") or "",
                    pitch.findtext("alter") or "0",
                    note.findtext("staff") or "1",
                )
                voice_el = note.find("voice")
                voice = voice_el.text if voice_el is not None else "1"
                for tie in note.findall("tie"):
                    typ = tie.get("type")
                    if typ == "start":
                        open_ties[key] = voice
                    elif typ == "stop":
                        expected = open_ties.pop(key, None)
                        if expected is not None and expected != voice and voice_el is not None:
                            voice_el.text = expected
                            rewrites += 1
```

Replace with:

```python
    parser = ET.XMLParser()
    root = ET.fromstring(raw, parser=parser)

    rewrites = 0
    for part in root.findall("part"):
        # Ties never cross hands. Reset the open-tie map for each <part>
        # so an RH tie-start can't "match" an LH same-pitch attack in
        # the two-part encoding (where <staff> tags are absent and the
        # old (pitch, staff) key degenerated to (pitch,)).
        open_ties: dict[tuple[str, str, str], str] = {}
        for measure in part.findall("measure"):
            for note in measure.findall("note"):
                pitch = note.find("pitch")
                if pitch is None:
                    continue
                key = (
                    pitch.findtext("step") or "",
                    pitch.findtext("octave") or "",
                    pitch.findtext("alter") or "0",
                )
                voice_el = note.find("voice")
                voice = voice_el.text if voice_el is not None else "1"
                for tie in note.findall("tie"):
                    typ = tie.get("type")
                    if typ == "start":
                        open_ties[key] = voice
                    elif typ == "stop":
                        expected = open_ties.pop(key, None)
                        if expected is not None and expected != voice and voice_el is not None:
                            voice_el.text = expected
                            rewrites += 1
```

Also update the docstring at lines 786–796. Find:

```python
    """Rewrite tie-stop / tie-continue notes to match the voice of the
    preceding tie-start for the same (pitch, staff).
    ...
    ... track open ties by ``(step, octave, alter,
    staff)``, and when we see a note that closes an open tie, rewrite
    its ``<voice>`` tag to match the start.
    """
```

Replace with:

```python
    """Rewrite tie-stop / tie-continue notes to match the voice of the
    preceding tie-start for the same pitch within the same ``<part>``.

    music21 sometimes assigns a bar-crossing note's continuation to a
    different voice in the next measure. After the voice-clamp step
    this shows up as tie-start on voice 1, tie-stop on voice 2 — which
    MuseScore 4 reports as a dangling tie corruption. We walk the XML
    part by part (ties never cross hands), tracking open ties by
    ``(step, octave, alter)``, and rewrite the tie-stop's ``<voice>``
    tag to match the tie-start's voice.
    """
```

- [ ] **Step 4: Run the tie-chain test plus the full existing engrave test module**

```bash
pytest tests/test_engrave_quality.py -v
```

Expected: all tests PASS, including:
- the new `test_l2_tie_chain_per_part_isolation`,
- the rewritten `test_l2_grand_staff_two_parts_braced`,
- the rewritten `test_l2_rh_only_fixture_still_braced`,
- the new `test_l2_bass_range_lh_renders_on_bass_clef_part`,
- all pre-existing L1/L2 tests (voice numbering, divisions, pitches, note counts, dynamics, pedal, fermata, bar-crossing ties, etc.).

If `test_l2_two_voices_preserved_on_same_staff` fails, the per-part voice remapper in `_remap_voices_per_staff` is the culprit — go to Task 6.

---

## Task 6: Document that `_remap_voices_per_staff` now degenerates to per-part remapping

**Files:**
- Modify: `backend/services/engrave.py:719-782`.

In the new encoding there are no `<staff>` tags. The function's `staff_el.text if staff_el is not None else cur_staff` fallback makes every note default to staff `"1"`, so voices end up grouped per-`<part>` — which is the correct unit under two-part encoding. The behavior is preserved; only the mental model changes. Add a docstring note so future readers aren't confused.

- [ ] **Step 1: Update the docstring**

Find `_remap_voices_per_staff` at line 719 and update its docstring. Current:

```python
def _remap_voices_per_staff(raw: bytes) -> bytes:
    """Renumber voice tags per staff so each staff uses ``{1, 2}``.

    music21's exporter numbers voices globally within a ``<part>``
    — a grand staff with two voices per hand gets voices ``{1..4}``.
    ...
    """
```

Replace the docstring with:

```python
def _remap_voices_per_staff(raw: bytes) -> bytes:
    """Renumber voice tags per ``<part>`` so each part uses ``{1, 2}``.

    Legacy contract: music21's exporter numbers voices globally within
    a ``<part>`` — a grand staff with two voices per hand gets voices
    ``{1..4}``. OSMD's VexFlow backend crashes on ``voice ≥ 3``, so we
    compress to ``{1, 2}`` per grouping unit.

    Under the current two-part / brace encoding there is no ``<staff>``
    element (each hand is its own ``<part>``), so the function's
    ``staff = staff_el.text if staff_el is not None else cur_staff``
    fallback collapses every note to the synthetic staff ``"1"`` — which
    is exactly the per-part scope we want. The function continues to
    work correctly; the ``per_staff`` name is historical.

    Keeps defense-in-depth for any future path (e.g. condense) that may
    emit 3+ voices on a hand. Safe to keep; cheap to run.
    """
```

(No code change — behavior is preserved by the existing fallback.)

- [ ] **Step 2: Run the full engrave quality test suite again**

```bash
pytest tests/test_engrave_quality.py -v
```

Expected: all PASS. Confirms the docstring update didn't disturb anything.

---

## Task 7: Run lint, typecheck, and the full test suite

**Files:** none (gate step).

- [ ] **Step 1: Lint**

Run:

```bash
make lint
```

Expected: clean. If ruff complains about an unused import (e.g., a `PartStaff` reference that's no longer needed — unlikely since the change is localized), fix it inline.

- [ ] **Step 2: Typecheck**

Run:

```bash
make typecheck
```

Expected: clean. `music21.stream.Part` and `PartStaff` share the same `Stream` base — any signature mismatch would be a stub issue, not a real type error. If mypy flags a line, cast narrowly at the call site (`cast("music21.stream.Stream", part)`) rather than broadening the function signature.

- [ ] **Step 3: Full test suite**

Run:

```bash
make test
```

Expected: every test in the suite passes. The change is localized to `engrave.py` — consumers of `EngravedOutput` (artifact download, job manager) are unaffected, but a green full run confirms no unexpected consumer parses the MusicXML's `<staves>` element.

---

## Task 8: Manual PDF verification on the failing Bob Marley job

**Files:** none (manual smoke).

The regression test pins the MusicXML encoding; this step confirms the rendered PDF looks correct end-to-end. LilyPond must be installed locally (`brew install lilypond` on macOS, `apt install lilypond` on Linux). If only MuseScore is installed, the smoke still works — MuseScore also renders the new encoding correctly.

- [ ] **Step 1: Re-render the Bob Marley score from its blob snapshot**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path
from backend.contracts import HumanizedPerformance
from backend.services.engrave import _engrave_sync

# Load the humanized performance that was the input to engrave on that job.
raw = json.loads(Path("blob/jobs/f255d56b4243/engrave/input.json").read_text())
payload = HumanizedPerformance.model_validate(raw["payload"])
pdf, musicxml, midi, _chords = _engrave_sync(payload, title="bob-marley-rerender", composer="")
Path("/tmp/bob_rerender.pdf").write_bytes(pdf)
Path("/tmp/bob_rerender.musicxml").write_bytes(musicxml)
print("PDF bytes:", len(pdf), "at /tmp/bob_rerender.pdf")
print("MusicXML bytes:", len(musicxml), "at /tmp/bob_rerender.musicxml")
PY
```

Expected: `PDF bytes: 80000+`, real PDF (not the 60-byte stub).

- [ ] **Step 2: Open the PDF and verify the grand staff**

```bash
open /tmp/bob_rerender.pdf   # macOS; xdg-open on Linux
```

Verify:
1. The top staff has a **treble clef** with notes in a reasonable range (C4–E6), not drowning in ledger lines.
2. The bottom staff has a **bass clef**.
3. The time signature (`4/4`) appears at the start of **both** staves, aligned with the clefs — not floating in a weird spot.
4. A brace joins the two staves on the left.
5. The left-hand notes are in the bass-clef range (E2–B3) and sit mostly within the staff with at most a few ledger lines.

If any of these fail, stop and diagnose before committing. Inspect `/tmp/bob_rerender.musicxml` to confirm the encoding is as expected (two `<part>` elements, `<part-group>` with brace, G clef on part 1, F clef on part 2).

- [ ] **Step 3: Smoke-test a simpler fixture for regression**

```bash
python - <<'PY'
from pathlib import Path
from backend.services.engrave import _engrave_sync
from tests.fixtures import load_score_fixture

score = load_score_fixture("c_major_scale")
pdf, _xml, _midi, _chords = _engrave_sync(score, title="smoke", composer="pytest")
Path("/tmp/c_major_rerender.pdf").write_bytes(pdf)
print("PDF bytes:", len(pdf))
PY
open /tmp/c_major_rerender.pdf
```

Expected: a clean grand-staff rendering of a C major scale — treble clef top, bass clef bottom, brace on the left. No regression on the simple case.

---

## Task 9: Commit the full change

**Files:** none (commit step).

- [ ] **Step 1: Confirm the tree is clean apart from the intended files**

Run:

```bash
git status
```

Expected modifications:
- `backend/services/engrave.py`
- `tests/test_engrave_quality.py`

If anything else is modified, revert it before committing.

- [ ] **Step 2: Commit**

```bash
git add backend/services/engrave.py tests/test_engrave_quality.py
git commit -m "$(cat <<'EOF'
feat(engrave): emit two-part braced grand staff for LilyPond

Replace music21 PartStaff (one <part>/<staves>2</staves>) with two Part
objects wrapped in the same StaffGroup(symbol='brace'). musicxml2ly did
not reliably honor the one-part/multi-staff encoding: the LH clef was
dropped and LilyPond rendered both staves with a treble clef, producing
huge ledger-line stacks for left-hand notes and a floating time
signature on job f255d56b4243 (YouTube oFRbZJXjWIA).

The two-part + brace encoding is the canonical MusicXML idiom for a
piano grand staff and is rendered identically by LilyPond (via
musicxml2ly), MuseScore, Verovio, and OSMD.

Changes:
- backend/services/engrave.py: PartStaff -> Part in _render_musicxml_bytes;
  StaffGroup 'Piano' name now owns the label so per-part names are empty;
  _align_tie_chain_voices scopes open_ties per <part>; docstring updated
  on _remap_voices_per_staff to note behavior under the new encoding.
- tests/test_engrave_quality.py: rewrite grand-staff structure tests for
  two-part encoding; add regression test for the Bob Marley failure
  mode; add tie-chain per-part isolation test.
EOF
)"
```

- [ ] **Step 3: Post-merge verification**

After merging to main, re-process job `f255d56b4243` through the full pipeline (POST a fresh job with the same YouTube URL) and confirm the final PDF artifact shows the corrected grand staff. Record the new job id in the PR description.
