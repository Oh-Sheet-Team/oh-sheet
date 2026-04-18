# Refine: filename fallback + common-sense heuristics

## Problem

When the user supplies neither `title` nor `artist`, the refine stage's LLM
has no way to identify the song and typically returns an empty
`submit_refinements` call (or nothing at all), producing no metadata
improvements. Uploaded files almost always carry a descriptive filename
(e.g., `my-heart-will-go-on-humanized.mid`), which we currently discard
at the upload boundary.

## Change

1. **Carry the original filename through the contract.**
   - `RemoteAudioFile.source_filename: str | None = None`
   - `RemoteMidiFile.source_filename: str | None = None`
   - `InputMetadata.source_filename: str | None = None`
2. **Populate at upload.** `POST /v1/uploads/{audio,midi}` copies
   `UploadFile.filename` into the returned Remote\*File.
3. **Forward at job creation.** `POST /v1/jobs` lifts `source_filename`
   off the supplied Remote\*File into `InputMetadata`.
4. **Feed refine.** `PipelineRunner` adds `filename_hint` to the refine
   envelope; `refine` worker + `RefineService.run` thread it into
   `build_user_prompt`.
5. **Prompt updates.**
   - User prompt includes a `filename=<name>` line alongside title/artist.
   - System prompt adds a "never return empty" rule: when identification
     fails, the LLM MUST still call `submit_refinements` with common-sense
     defaults derived from the detected data — `tempo_marking` from BPM
     (Largo ≤60, Andante ~76, Moderato ~108, Allegro ~120, Presto ≥168),
     `staff_split_hint=60`, keep detected key/time signature, and use the
     filename (minus extension) as `title` if nothing better is known.

## Non-goals

- No deterministic/rule-based fallback path that bypasses the LLM.
  Heuristics are LLM-driven via prompt instructions.
- No new eval fixtures; existing `refine_golden/` tests still apply.
- No change to the refine cache key format (filename is already part of
  the payload hash upstream via `InputMetadata`).

## Tests

- `test_refine_prompt.py`: assert the prompt renders `filename=...` when
  `filename_hint` is provided, and that the heuristic instruction is
  present in `SYSTEM_PROMPT`.
- Existing `test_refine_service.py` passes unchanged (new arg is
  optional).
- `test_uploads.py`: assert `source_filename` round-trips through the
  upload endpoints.
