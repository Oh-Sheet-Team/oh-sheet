"""Verify the Celery app can be imported and configured."""
from backend.workers.celery_app import celery_app


def test_celery_app_name():
    assert celery_app.main == "ohsheet"


def test_celery_app_broker_from_settings():
    """Broker URL should come from settings.redis_url."""
    # Default is redis://localhost:6379/0
    assert "redis" in celery_app.conf.broker_url


def test_refine_run_routes_to_refine_queue():
    """WR-03 regression: refine.run must have an explicit task-route entry so
    dedicated `celery -Q refine` workers pick up refine tasks instead of
    silently falling through to the default queue.
    """
    routes = celery_app.conf.task_routes
    assert "refine.run" in routes, "refine.run missing from task_routes"
    assert routes["refine.run"] == {"queue": "refine"}


def test_all_stage_tasks_have_dedicated_routes():
    """Sanity: every pipeline stage task routes to a named queue (not default)."""
    routes = celery_app.conf.task_routes
    expected = {
        "ingest.run", "transcribe.run", "arrange.run",
        "condense.run", "transform.run", "humanize.run",
        "refine.run", "engrave.run",
    }
    assert expected.issubset(routes.keys())
