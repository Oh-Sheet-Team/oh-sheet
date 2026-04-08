"""Application settings.

All values can be overridden via environment variables prefixed with
``OHSHEET_`` (e.g. ``OHSHEET_BLOB_ROOT=/var/lib/ohsheet/blob``).
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OHSHEET_",
        env_file=".env",
        extra="ignore",
    )

    # Where the LocalBlobStore writes its files. Returned URIs are file:// based.
    blob_root: Path = Path("./blob")

    # CORS — wide open for dev; tighten in deployment.
    cors_origins: list[str] = ["*"]

    # Worker timeout used by OrchestratorCommand envelopes.
    job_timeout_sec: int = 600

    # ---- Basic Pitch transcription -----------------------------------------
    # Tunable knobs passed through to basic_pitch.inference.predict(). Defaults
    # mirror upstream (basic_pitch.constants.DEFAULT_*). The ONNX model ships
    # inside the basic-pitch wheel, so there's no checkpoint path to configure.
    basic_pitch_onset_threshold: float = 0.5
    basic_pitch_frame_threshold: float = 0.3
    basic_pitch_minimum_note_length_ms: float = 127.7

    # ---- Transcription cleanup (Phase 1 post-processing) -------------------
    # Heuristic thresholds applied to Basic Pitch's note_events before we
    # rebuild pretty_midi. See backend/services/transcription_cleanup.py for
    # the semantics; these pass through as keyword args to cleanup_note_events.
    cleanup_merge_gap_sec: float = 0.03
    cleanup_octave_amp_ratio: float = 0.6
    cleanup_octave_onset_tol_sec: float = 0.05
    cleanup_ghost_max_duration_sec: float = 0.06
    cleanup_ghost_amp_median_scale: float = 0.5

    # ---- Melody extraction (Phase 2 post-processing) -----------------------
    # Viterbi-based melody / chord split driven by Basic Pitch's
    # ``model_output["contour"]`` salience matrix. See
    # backend/services/melody_extraction.py for semantics. Disable via
    # ``OHSHEET_MELODY_EXTRACTION_ENABLED=false`` to keep the legacy
    # single-PIANO output. Defaults mirror the DEFAULT_* constants in the
    # extraction module so config and tests agree.
    melody_extraction_enabled: bool = True
    melody_low_midi: int = 55                    # G3
    melody_high_midi: int = 90                   # F#6
    melody_voicing_floor: float = 0.15
    melody_transition_weight: float = 0.25
    melody_max_transition_bins: int = 12         # ≈ 4 semitones / frame
    melody_match_fraction: float = 0.6


settings = Settings()
