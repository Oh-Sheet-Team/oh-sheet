"""Model runners — how a chunk of performance notes becomes a score.

Two implementations:

* ``StubModelRunner`` — no ML dependency. Translates PerfNotes directly
  into a music21 score by snapping onsets to a 16th-note grid. Lets the
  service boot and be tested without torch / rl_model.

* ``Seq2SeqModelRunner`` — the real one. Lazy-imports ``rl_model`` at
  ``load()`` time so the service image can ship without torch for
  environments that only want the stub path. Runs the full diagram-§5
  inference flow:

      encode_perf → model.encode → init_decode_cache
        → FSM-masked decode loop → vocab.decode_tokens
        → tokenize.decode_events → music21.Score

  Parse failures (the §6 "parse gate") are caught per-chunk and reported
  in ``ScoreChunk.parse_failed`` so the service can log the failure and
  skip that measure range instead of poisoning the whole request.
"""
from __future__ import annotations

import logging
import time
from typing import Protocol

from inference.config import Settings
from inference.midi_pipeline import PerfChunk, PerfNote, ScoreChunk

log = logging.getLogger(__name__)


class ModelRunner(Protocol):
    name: str

    def load(self) -> None: ...
    def transcribe_chunk(self, chunk: PerfChunk) -> ScoreChunk: ...


# ---------------------------------------------------------------------------
# Stub runner — no ML deps
# ---------------------------------------------------------------------------

class StubModelRunner:
    """Deterministic non-ML runner for local dev and tests.

    Snaps each PerfNote onset to the nearest 16th note and emits a
    flat music21 score. Fakes beam-search stats so the logging path
    is exercised end-to-end.
    """
    name = "stub"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._loaded = False

    def load(self) -> None:
        # No-op: stub has nothing to warm up. We still flip the flag so
        # /health can distinguish "runner selected but not loaded yet".
        self._loaded = True

    def transcribe_chunk(self, chunk: PerfChunk) -> ScoreChunk:
        if not self._loaded:
            raise RuntimeError("StubModelRunner.load() was not called")

        try:
            from music21 import note, stream  # noqa: PLC0415
        except ImportError:
            # music21 missing → return an empty shell; stitcher will
            # fall back to the minimal MusicXML path using chunk.notes.
            return ScoreChunk(
                chunk=chunk, score=None, decode_steps=0,
                rejected_tokens=0, parse_failed=False,
                notes_emitted=len(chunk.notes),
            )

        sec_per_beat = 60.0 / 120.0  # stub assumes 120 BPM normalization
        s = stream.Stream()
        for pn in chunk.notes:
            rel_beat = max(0.0, (pn.onset_sec - chunk.start_beat * sec_per_beat) / sec_per_beat)
            rel_beat = round(rel_beat * 4) / 4.0  # snap to 16th
            dur_beat = max(0.25, (pn.offset_sec - pn.onset_sec) / sec_per_beat)
            dur_beat = round(dur_beat * 4) / 4.0
            n = note.Note(midi=pn.pitch)
            n.quarterLength = dur_beat
            n.volume.velocity = pn.velocity
            s.insert(rel_beat, n)

        return ScoreChunk(
            chunk=chunk, score=s,
            decode_steps=len(chunk.notes) * 4,  # 4 tokens/note burst
            rejected_tokens=0,
            parse_failed=False,
            notes_emitted=len(chunk.notes),
        )


# ---------------------------------------------------------------------------
# Seq2Seq runner — real model
# ---------------------------------------------------------------------------

class Seq2SeqModelRunner:
    """FSM-constrained Seq2Seq decoder wired to rl_model.

    Requires the external ``rl_model`` package (separate repo) and
    ``torch``. Loads the checkpoint once at ``load()`` time; every
    ``transcribe_chunk`` call reuses the warm model.
    """
    name = "seq2seq"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._loaded = False
        self._model = None
        self._grammar_cls = None
        self._midi_vocab = None
        self._vocab = None
        self._tokenize_mod = None
        self._torch = None
        self._device = None

    def load(self) -> None:
        if self._loaded:
            return
        t0 = time.perf_counter()
        try:
            import torch  # noqa: PLC0415
            from rl_model import grammar as grammar_mod  # noqa: PLC0415
            from rl_model import midi_vocab, tokenize, vocab  # noqa: PLC0415
            from rl_model.modeling.seq2seq import Seq2Seq  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "Seq2SeqModelRunner requires `torch` and the `rl_model` package. "
                "Install them or switch OHSHEET_INFERENCE_RUNNER=stub."
            ) from exc

        if not self.settings.checkpoint_uri:
            raise RuntimeError(
                "OHSHEET_INFERENCE_CHECKPOINT_URI is required for the seq2seq runner"
            )

        self._torch = torch
        self._device = torch.device(self.settings.device)
        self._midi_vocab = midi_vocab
        self._vocab = vocab
        self._tokenize_mod = tokenize
        self._grammar_cls = grammar_mod.GrammarFSM

        checkpoint = torch.load(self.settings.checkpoint_uri, map_location=self._device)
        model = Seq2Seq.from_checkpoint(checkpoint) if hasattr(Seq2Seq, "from_checkpoint") else checkpoint["model"]
        model.to(self._device).eval()
        self._model = model
        self._loaded = True

        log.info(
            "seq2seq runner loaded",
            extra={
                "checkpoint_uri": self.settings.checkpoint_uri,
                "device": str(self._device),
                "load_ms": round((time.perf_counter() - t0) * 1000, 1),
            },
        )

    def transcribe_chunk(self, chunk: PerfChunk) -> ScoreChunk:
        if not self._loaded:
            raise RuntimeError("Seq2SeqModelRunner.load() was not called")
        torch = self._torch
        assert torch is not None

        src_ids = self._encode_chunk(chunk)
        if src_ids is None or len(src_ids) == 0:
            return ScoreChunk(chunk=chunk, score=None, parse_failed=False)

        with torch.no_grad():
            src = torch.tensor([src_ids], dtype=torch.long, device=self._device)
            memory, src_pad = self._model.encode(src)  # type: ignore[union-attr]
            cache = self._model.init_decode_cache(memory, src_pad, self.settings.max_tgt_tokens)  # type: ignore[union-attr]

            fsm = self._grammar_cls()  # type: ignore[misc]
            ys: list[int] = [self._vocab.BOS_ID]  # type: ignore[union-attr]
            rejected = 0
            eos_id = getattr(self._vocab, "EOS_ID", None)

            for step in range(self.settings.max_tgt_tokens):
                logits = self._model.decode_step_cached(  # type: ignore[union-attr]
                    torch.tensor([[ys[-1]]], device=self._device),
                    cache,
                )
                logits = logits[0, -1] / max(1e-6, self.settings.decode_temperature)
                mask = fsm.legal_mask(ys)
                if mask is not None:
                    mask_t = torch.as_tensor(mask, device=logits.device, dtype=torch.bool)
                    rejected += int((~mask_t).sum().item())
                    logits = logits.masked_fill(~mask_t, float("-inf"))
                next_id = int(torch.argmax(logits).item())
                ys.append(next_id)
                fsm.advance(next_id)
                if eos_id is not None and next_id == eos_id:
                    break

        events = self._vocab.decode_tokens(ys)  # type: ignore[union-attr]

        parse_failed = False
        score = None
        try:
            score = self._tokenize_mod.decode_events(events)  # type: ignore[union-attr]
        except Exception as exc:  # parse gate
            if self.settings.parse_gate_enabled:
                parse_failed = True
                log.warning(
                    "parse_gate_failure",
                    extra={
                        "chunk_index": chunk.index,
                        "decode_steps": len(ys),
                        "exc": str(exc),
                    },
                )
            else:
                raise

        return ScoreChunk(
            chunk=chunk,
            score=score,
            decode_steps=len(ys),
            rejected_tokens=rejected,
            parse_failed=parse_failed,
            notes_emitted=len(chunk.notes),
        )

    def _encode_chunk(self, chunk: PerfChunk) -> list[int] | None:
        """Call rl_model.midi_vocab.encode_perf on the chunk's PerfNotes."""
        if not chunk.notes:
            return []
        try:
            ids = self._midi_vocab.encode_perf([  # type: ignore[union-attr]
                _as_rl_perfnote(n) for n in chunk.notes
            ])
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "encode_perf failed",
                extra={"chunk_index": chunk.index, "exc": str(exc)},
            )
            return None
        if len(ids) > self.settings.max_src_tokens:
            log.warning(
                "chunk exceeds max_src_tokens — truncating",
                extra={"chunk_index": chunk.index, "src_len": len(ids)},
            )
            ids = ids[: self.settings.max_src_tokens]
        return list(ids)


def _as_rl_perfnote(pn: PerfNote) -> object:
    """Adapt our PerfNote to whatever shape rl_model.midi_vocab expects.

    The diagram shows rl_model.core.PerfNote as (pitch, on/off, vel);
    our fields (pitch, onset_sec, offset_sec, velocity) match that shape
    so the adapter is a straight namedtuple-style call. We import
    lazily to avoid pulling rl_model into module load.
    """
    try:
        from rl_model.core import PerfNote as RlPerfNote  # noqa: PLC0415
        return RlPerfNote(
            pitch=pn.pitch,
            onset=pn.onset_sec,
            offset=pn.offset_sec,
            velocity=pn.velocity,
        )
    except Exception:  # noqa: BLE001 — rl_model variants may differ
        return pn


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_runner(settings: Settings) -> ModelRunner:
    if settings.runner == "stub":
        return StubModelRunner(settings)
    if settings.runner == "seq2seq":
        return Seq2SeqModelRunner(settings)
    raise ValueError(f"unknown runner: {settings.runner!r}")
