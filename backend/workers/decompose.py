"""Celery task for the decompose pipeline stage."""
from shared.contracts import TranscriptionResult
from shared.storage.local import LocalBlobStore

from backend.config import settings
from backend.services.decompose import DecomposeService
from backend.workers.celery_app import celery_app


@celery_app.task(name="decompose.run")
def run(job_id: str, payload_uri: str) -> str:
    blob = LocalBlobStore(settings.blob_root)
    raw = blob.get_json(payload_uri)
    txr = TranscriptionResult.model_validate(raw)

    service = DecomposeService()
    result = service.run(txr)

    output_uri = blob.put_json(
        f"jobs/{job_id}/decompose/output.json",
        result.model_dump(mode="json"),
    )
    return output_uri
