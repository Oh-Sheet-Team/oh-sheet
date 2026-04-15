"""Runtime settings for the inference microservice."""
from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OHSHEET_INFERENCE_", env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8080

    runner: Literal["stub", "seq2seq"] = "stub"
    checkpoint_uri: str | None = None
    device: Literal["cpu", "cuda", "mps"] = "cpu"

    max_workers: int = 4

    chunk_window_beats: float = 32.0
    chunk_stride_beats: float = 24.0
    max_src_tokens: int = 8192
    max_tgt_tokens: int = 16384

    beam_width: int = 1
    decode_temperature: float = 1.0
    parse_gate_enabled: bool = True

    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
