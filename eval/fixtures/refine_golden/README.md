# Refine Golden Set

A small set of canonical songs used by `scripts/eval_refine.py` to score
the refine stage against human-curated ground truth.

## Fixture layout

Each song gets a directory with two files:

    eval/fixtures/refine_golden/<slug>/
        input_score.json     # PianoScore JSON — the refine stage's input
        ground_truth.json    # expected title/composer/key/time/tempo/sections/repeats

## Authoring a new fixture

1. Pick a song whose title / composer / key / form are unambiguous and
   findable by a competent researcher (Wikipedia, IMSLP, sheet-music
   databases). Prefer classical, standard jazz, and well-documented
   pop/game OST over obscure bootlegs.
2. Generate a plausible `PianoScore` via the pipeline or by hand — it
   should have the approximate measure count, detected (wrong-ish) key,
   detected time signature, and per-beat chord symbols of a real
   transcription of the song. The notes themselves don't need to match
   the recording precisely; refine only sees the digest.
3. Fill in `ground_truth.json` with:
   - `title` (string)
   - `composer` (string)
   - `key_signature` (string, Harte notation)
   - `time_signature` ([numerator, denominator])
   - `tempo_bpm` (number)
   - `sections` (list of `{start_beat, end_beat, label}`)
   - `repeats` (list of `{start_beat, end_beat, kind}`)
4. Run `make eval-refine` — the new fixture's metrics will be added
   to `refine-baseline.json`.

Target: 10–15 fixtures spanning genres. Seed fixture: Clair de Lune.
