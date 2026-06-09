"""
celery_app.py — Celery application factory for Lumiq.

Creates and configures the Celery instance. Kept separate from app.py
to avoid circular imports (tasks.py imports celery; app.py imports tasks).

Usage (from tasks.py):
    from celery_app import make_celery

Usage (CLI):
    celery -A tasks.celery worker --loglevel=info --concurrency=2
    celery -A tasks.celery flower --port=5555
"""

from celery import Celery


def make_celery(flask_app) -> Celery:
    """
    Create a Celery instance bound to the given Flask app.

    All tasks run inside a Flask application context so they can
    access db, config, and extensions (e.g. socketio) transparently.
    """
    celery = Celery(
        flask_app.import_name,
        broker=flask_app.config["CELERY_BROKER_URL"],
        backend=flask_app.config["CELERY_RESULT_BACKEND"],
    )

    # Push all CELERY_* keys from Flask config into Celery
    celery.conf.update(
        {k: v for k, v in flask_app.config.items() if k.startswith("CELERY_")}
    )

    # ── ContextTask: every task runs inside a Flask app context ───────────────
    class ContextTask(celery.Task):
        """Celery base task that pushes a Flask app context."""

        abstract = True

        def __call__(self, *args, **kwargs):
            with flask_app.app_context():
                return self.run(*args, **kwargs)

        def on_failure(self, exc, task_id, args, kwargs, einfo):
            """Log unhandled task failures to the application logger."""
            import logging
            logging.getLogger(__name__).error(
                "Celery task %s failed: %s\n%s", task_id, exc, einfo
            )

    celery.Task = ContextTask
    return celery
