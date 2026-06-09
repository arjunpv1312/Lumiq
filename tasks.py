"""
tasks.py — Celery task definitions for Lumiq.

This module defines the background pipeline task that replaces the
Python threading implementation previously in app.py.

Design: Celery is created WITHOUT importing app.py at module level,
which prevents circular imports. The Flask app context is pushed
inside each task via the ContextTask base class in celery_app.py.

Worker startup:
    celery -A tasks worker --loglevel=info --concurrency=2

Flower monitoring:
    celery -A tasks flower --port=5555
"""

import logging
import os
import traceback

logger = logging.getLogger(__name__)


# ── Create Celery instance without importing app.py ────────────────────────────
# We create the Flask app independently here so that:
#   1. tasks.py can be the Celery entrypoint (-A tasks)
#   2. app.py can lazy-import run_pipeline without a circular import
def _create_celery():
    from flask import Flask
    from flask_socketio import SocketIO
    from config import get_config
    from models import db, init_db
    from celery_app import make_celery

    cfg = get_config()

    _app = Flask(__name__)
    _app.config.from_object(cfg)

    # Minimal init — just DB and SocketIO for worker context
    init_db(_app)

    # Async mode detection (gevent for production, threading for dev/Windows)
    _async_mode = cfg.SOCKETIO_ASYNC_MODE
    if _async_mode == "gevent":
        try:
            import gevent  # noqa: F401
        except ImportError:
            _async_mode = "threading"

    _sio = SocketIO(
        _app,
        async_mode=_async_mode,
        message_queue=cfg.SOCKETIO_MESSAGE_QUEUE,
        logger=False,
        engineio_logger=False,
    )

    _celery = make_celery(_app)
    return _celery, _sio


celery, _socketio = _create_celery()


# ── Progress helpers ───────────────────────────────────────────────────────────

def _emit(job_id: str, status: str, pct: int, message: str = "") -> None:
    """
    Push a progress event to all WebSocket clients subscribed to job_id.
    Falls back silently if SocketIO is unavailable (e.g. no Redis).
    """
    try:
        _socketio.emit(
            "progress_update",
            {"status": status, "pct": pct, "message": message, "job_id": job_id},
            room=job_id,
            namespace="/jobs",
        )
    except Exception as exc:
        logger.debug("SocketIO emit skipped: %s", exc)


def _store_and_emit(job_id: str, data: dict, message: str = "") -> None:
    """Persist status to DB and push a WebSocket event atomically."""
    from models import store_result
    store_result(job_id, data)
    _emit(job_id, data.get("status", ""), data.get("pct", 0), message)


# ── Main pipeline task ────────────────────────────────────────────────────────

@celery.task(
    bind=True,
    name="tasks.run_pipeline",
    max_retries=2,
    default_retry_delay=10,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_pipeline(self, job_id: str, filepath: str, filename: str) -> dict:
    """
    Execute the full Lumiq analytics pipeline as a Celery task.

    Stages:
        cleaning (8%) → eda (20%) → sentiment (40%) → topics (60%) →
        dashboard (70%) → wordcloud (78%) → insights (84%) →
        excel (90%) → pdf (95%) → done (100%)
    """
    from models import store_result, AuditLog

    logger.info("Pipeline started — job_id=%s, task_id=%s", job_id, self.request.id)

    store_result(job_id, {
        "status": "starting",
        "pct": 3,
        "celery_task_id": self.request.id,
        "filename": filename,
    })
    _emit(job_id, "starting", 3, "Initializing pipeline…")

    try:
        from modules.cleaner       import clean_data
        from modules.eda           import run_eda
        from modules.sentiment     import run_sentiment, clean_series, vader_batch, detect_ground_truth
        from modules.dashboard     import run_dashboard
        from modules.wordcloud_gen import generate_wordclouds
        from modules.insights      import generate_insights
        from modules.pdf_report    import generate_pdf
        from modules.topic_model   import extract_topics
        from modules.excel_export  import generate_excel
        from storage               import get_storage

        storage = get_storage()

        # ── Stage 1: Cleaning ─────────────────────────────────────────────────
        _store_and_emit(job_id, {"status": "cleaning", "pct": 8}, "Cleaning data…")
        df, clean_path, clean_meta = clean_data(filepath)

        clean_key = f"outputs/{job_id}/cleaned.csv"
        storage.save(clean_path, clean_key)
        resolved_clean_path = storage.get_url(clean_key)

        # ── Stage 2: EDA ──────────────────────────────────────────────────────
        _store_and_emit(job_id, {"status": "eda", "pct": 20}, "Running exploratory analysis…")
        eda_stats = run_eda(df, clean_meta)

        # ── Stage 3: Sentiment ────────────────────────────────────────────────
        _store_and_emit(job_id, {"status": "sentiment", "pct": 40}, "Analysing sentiment…")
        sentiment_stats = run_sentiment(df)

        if sentiment_stats.get("available") and "text_column" in sentiment_stats:
            text_col = sentiment_stats["text_column"]
            df["clean_text"] = clean_series(df[text_col])
            df["vader_label"] = vader_batch(df["clean_text"].tolist())
            gt_col, gt_type = detect_ground_truth(df)
            if gt_col:
                if gt_type == "rating":
                    def _rating_to_sent(r):
                        try:
                            val = float(r)
                            return "Positive" if val >= 4.0 else ("Negative" if val <= 2.0 else "Neutral")
                        except Exception:
                            return "Neutral"
                    df["target_label"] = df[gt_col].apply(_rating_to_sent)
                else:
                    def _std_sent(s):
                        s = str(s).strip().lower()
                        if s in ["positive", "pos", "1", "2", "4", "5", "good"]: return "Positive"
                        if s in ["negative", "neg", "0", "bad"]:                  return "Negative"
                        return "Neutral"
                    df["target_label"] = df[gt_col].apply(_std_sent)
            else:
                df["target_label"] = df["vader_label"]

        # ── Stage 4: Topics ───────────────────────────────────────────────────
        _store_and_emit(job_id, {"status": "topics", "pct": 60}, "Extracting topics…")
        text_col = sentiment_stats.get("text_column")
        topic_data = (
            extract_topics(df[text_col].dropna().tolist())
            if text_col and text_col in df.columns
            else {"available": False}
        )

        # ── Stage 5: Dashboard ────────────────────────────────────────────────
        _store_and_emit(job_id, {"status": "dashboard", "pct": 70}, "Building dashboard…")
        dashboard_charts = run_dashboard(df, sentiment_stats)

        # ── Stage 6: Word Clouds ──────────────────────────────────────────────
        _store_and_emit(job_id, {"status": "wordcloud", "pct": 78}, "Generating word clouds…")
        wc_paths = generate_wordclouds(sentiment_stats)

        # ── Stage 7: Insights ─────────────────────────────────────────────────
        _store_and_emit(job_id, {"status": "insights", "pct": 84}, "Generating insights…")
        insights = generate_insights(eda_stats, sentiment_stats)

        # ── Stage 8: Excel ────────────────────────────────────────────────────
        _store_and_emit(job_id, {"status": "excel", "pct": 90}, "Generating Excel report…")
        excel_path_local = generate_excel(filename, clean_path, eda_stats, sentiment_stats, insights)
        excel_key = f"outputs/{job_id}/report.xlsx"
        storage.save(excel_path_local, excel_key)
        resolved_excel_path = storage.get_url(excel_key)

        # ── Stage 9: PDF ──────────────────────────────────────────────────────
        _store_and_emit(job_id, {"status": "pdf", "pct": 95}, "Generating PDF report…")
        pdf_path_local = generate_pdf(filename, eda_stats, sentiment_stats, insights)
        pdf_key = f"outputs/{job_id}/report.pdf"
        storage.save(pdf_path_local, pdf_key)
        resolved_pdf_path = storage.get_url(pdf_key)

        # ── Done ──────────────────────────────────────────────────────────────
        final_result = {
            "status":           "done",
            "pct":              100,
            "celery_task_id":   self.request.id,
            "clean_path":       resolved_clean_path,
            "clean_key":        clean_key,
            "excel_path":       resolved_excel_path,
            "excel_key":        excel_key,
            "pdf_path":         resolved_pdf_path,
            "pdf_key":          pdf_key,
            "eda_stats":        eda_stats,
            "sentiment_stats":  sentiment_stats,
            "dashboard_charts": dashboard_charts,
            "wc_paths":         wc_paths,
            "insights":         insights,
            "topic_data":       topic_data,
            "sample_note":      clean_meta.get("sample_note", ""),
            "was_sampled":      clean_meta.get("was_sampled", False),
        }
        _store_and_emit(job_id, final_result, "Analysis complete!")
        logger.info("Pipeline completed — job_id=%s", job_id)
        AuditLog.log_event("pipeline", "Pipeline completed", "info", job_id=job_id)
        return {"status": "done", "job_id": job_id}

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("Pipeline failed — job_id=%s: %s\n%s", job_id, exc, tb)
        error_payload = {
            "status": "error", "pct": 0,
            "error": str(exc), "trace": tb,
            "celery_task_id": self.request.id,
        }
        _store_and_emit(job_id, error_payload, f"Error: {str(exc)[:120]}")
        AuditLog.log_event("pipeline_error", f"Pipeline failed: {exc}", "error", job_id=job_id)
        if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            raise self.retry(exc=exc)
        return {"status": "error", "job_id": job_id, "error": str(exc)}


# ── Periodic cleanup task ─────────────────────────────────────────────────────

@celery.task(name="tasks.cleanup_old_jobs")
def cleanup_old_jobs_task() -> dict:
    """Scheduled cleanup: deletes old job records and files."""
    from config import get_config
    from models import cleanup_old_jobs
    import os, time as _time
    from pathlib import Path

    cfg = get_config()
    db_deleted = cleanup_old_jobs(cfg.JOB_CLEANUP_AGE_HOURS)

    # Filesystem cleanup
    now = _time.time()
    max_age = cfg.JOB_CLEANUP_AGE_HOURS * 3600
    fs_deleted = 0
    for folder in [cfg.UPLOAD_FOLDER, cfg.OUTPUT_FOLDER]:
        if not Path(folder).exists():
            continue
        for f in Path(folder).iterdir():
            if f.is_file() and f.name not in ("sample_data.csv", "best_model.pkl"):
                if now - f.stat().st_mtime > max_age:
                    try:
                        f.unlink()
                        fs_deleted += 1
                    except Exception:
                        pass

    logger.info("Cleanup task: %d DB records, %d files removed", db_deleted, fs_deleted)
    return {"db_deleted": db_deleted, "fs_deleted": fs_deleted}
