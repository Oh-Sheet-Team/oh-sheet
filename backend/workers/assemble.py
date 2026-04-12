"""Celery task for the assemble pipeline stage."""
from shared.contracts import TranscriptionResult
from shared.storage.local import LocalBlobStore

from backend.config import settings
from backend.services.assemble import AssembleService
from backend.workers.celery_app import celery_app


@celery_app.task(name="assemble.run")
def run(job_id: str, payload_uri: str) -> str:
    blob = LocalBlobStore(settings.blob_root)
    raw = blob.get_json(payload_uri)

    # The runner wraps the payload in an envelope with difficulty.
    # If no envelope, treat raw as TranscriptionResult directly.
    if "transcription" in raw:
        txr = TranscriptionResult.model_validate(raw["transcription"])
        difficulty = raw.get("difficulty", settings.assemble_difficulty)
    else:
        txr = TranscriptionResult.model_validate(raw)
        difficulty = settings.assemble_difficulty

    service = AssembleService()
    result = service.run(txr, difficulty=difficulty)

    output_uri = blob.put_json(
        f"jobs/{job_id}/assemble/output.json",
        result.model_dump(mode="json"),
    )
    return output_uri
