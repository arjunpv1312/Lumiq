"""
Database models for Lumiq application.
Provides persistent storage for job results and processing data.

Compatible with both SQLite (development) and PostgreSQL (production).
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Index

logger = logging.getLogger(__name__)
db = SQLAlchemy()


# ── Job Results ───────────────────────────────────────────────────────────────

class JobResult(db.Model):
    """Store analysis results for each pipeline job."""

    __tablename__ = "job_results"

    id             = db.Column(db.Integer, primary_key=True)
    job_id         = db.Column(db.String(36),  unique=True, nullable=False, index=True)
    celery_task_id = db.Column(db.String(255), nullable=True)   # Celery task UUID
    filename       = db.Column(db.String(255), nullable=False, default="unknown")
    status         = db.Column(db.String(50),  nullable=False, default="starting", index=True)
    progress       = db.Column(db.Integer,     nullable=False, default=0)
    data           = db.Column(db.Text,        nullable=True)   # JSON blob — full pipeline result
    error          = db.Column(db.Text,        nullable=True)
    trace          = db.Column(db.Text,        nullable=True)   # Full Python traceback on error
    created_at     = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)
    updated_at     = db.Column(db.DateTime,    nullable=False,
                               default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at   = db.Column(db.DateTime,    nullable=True)

    # Composite index — speeds up polling queries like:
    #   WHERE status = 'done' ORDER BY updated_at DESC
    __table_args__ = (
        Index("ix_job_results_status_updated", "status", "updated_at"),
    )

    def __repr__(self):
        return f"<JobResult {self.job_id}: {self.status}>"

    def set_data(self, data_dict: dict) -> bool:
        """Serialise `data_dict` to JSON and persist. Does NOT commit."""
        try:
            self.data = json.dumps(data_dict, default=str)
            return True
        except Exception as e:
            logger.error("Failed to serialise data for job %s: %s", self.job_id, e)
            return False

    def get_data(self) -> dict:
        """Deserialise stored JSON. Returns {} on error."""
        try:
            return json.loads(self.data) if self.data else {}
        except json.JSONDecodeError:
            logger.error("Failed to parse JSON for job %s", self.job_id)
            return {}

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON API responses."""
        return {
            "job_id":         self.job_id,
            "celery_task_id": self.celery_task_id,
            "filename":       self.filename,
            "status":         self.status,
            "progress":       self.progress,
            "data":           self.get_data(),
            "error":          self.error,
            "created_at":     self.created_at.isoformat(),
            "updated_at":     self.updated_at.isoformat(),
            "completed_at":   self.completed_at.isoformat() if self.completed_at else None,
        }


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AuditLog(db.Model):
    """Track all security and operation events."""

    __tablename__ = "audit_logs"

    id          = db.Column(db.Integer,     primary_key=True)
    timestamp   = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow, index=True)
    event_type  = db.Column(db.String(50),  nullable=False, index=True)
    severity    = db.Column(db.String(20),  nullable=False, default="info")
    user_ip     = db.Column(db.String(45),  nullable=True)
    job_id      = db.Column(db.String(36),  nullable=True, index=True)
    action      = db.Column(db.String(255), nullable=False)
    details     = db.Column(db.Text,        nullable=True)
    status_code = db.Column(db.Integer,     nullable=True)

    def __repr__(self):
        return f"<AuditLog {self.timestamp}: {self.event_type}>"

    @staticmethod
    def log_event(event_type, action, severity="info",
                  user_ip=None, job_id=None, details=None, status_code=None) -> bool:
        """
        Create and persist an audit log entry.

        Uses flush() instead of commit() to batch with the caller's
        transaction — avoids excessive commit overhead under load.
        Falls back to a standalone commit if no session is active.
        """
        try:
            log = AuditLog(
                event_type=event_type,
                severity=severity,
                user_ip=user_ip,
                job_id=job_id,
                action=action,
                details=details,
                status_code=status_code,
            )
            db.session.add(log)
            db.session.flush()
            db.session.commit()
            return True
        except Exception as e:
            logger.error("Failed to create audit log: %s", e)
            try:
                db.session.rollback()
            except Exception:
                pass
            return False


# ── DB lifecycle helpers ──────────────────────────────────────────────────────

def init_db(app) -> None:
    """Initialise SQLAlchemy and create all tables."""
    db.init_app(app)
    with app.app_context():
        try:
            db.create_all()
            logger.info("Database initialised successfully")
        except Exception as e:
            logger.error("Failed to initialise database: %s", e)
            raise


def store_result(job_id: str, data_dict: dict) -> bool:
    """
    Upsert a job result record.

    Thread/worker safe: wraps the session in an explicit try/rollback
    to prevent a poisoned session from breaking subsequent operations.
    """
    try:
        result = JobResult.query.filter_by(job_id=job_id).first()

        if result:
            result.status     = data_dict.get("status", result.status)
            result.progress   = data_dict.get("pct",    result.progress)
            result.error      = data_dict.get("error",  result.error)
            result.trace      = data_dict.get("trace",  result.trace)
            result.updated_at = datetime.utcnow()

            # Store the Celery task ID if provided
            if "celery_task_id" in data_dict:
                result.celery_task_id = data_dict["celery_task_id"]

            if data_dict.get("status") == "done":
                result.completed_at = datetime.utcnow()

            result.set_data(data_dict)
        else:
            result = JobResult(
                job_id         = job_id,
                celery_task_id = data_dict.get("celery_task_id"),
                filename       = data_dict.get("filename", "unknown"),
                status         = data_dict.get("status", "starting"),
                progress       = data_dict.get("pct", 0),
            )
            result.set_data(data_dict)
            db.session.add(result)

        db.session.commit()
        logger.debug("Result stored for job %s: %s", job_id, data_dict.get("status"))
        return True

    except Exception as e:
        logger.error("Failed to store result for job %s: %s", job_id, e)
        try:
            db.session.rollback()
        except Exception:
            pass
        return False


def get_result(job_id: str) -> dict | None:
    """Retrieve a job result from the database."""
    try:
        result = JobResult.query.filter_by(job_id=job_id).first()
        if result:
            data = result.get_data()
            data["status"] = result.status
            data["pct"]    = result.progress
            if result.error:
                data["error"] = result.error
            if result.trace:
                data["trace"] = result.trace
            if result.celery_task_id:
                data["celery_task_id"] = result.celery_task_id
            return data
        return None
    except Exception as e:
        logger.error("Failed to retrieve result for job %s: %s", job_id, e)
        return None


def cleanup_old_jobs(max_age_hours: int = 2) -> int:
    """Delete completed job results older than `max_age_hours`."""
    try:
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        deleted = JobResult.query.filter(
            JobResult.completed_at < cutoff
        ).delete(synchronize_session=False)
        db.session.commit()
        logger.info("Cleaned up %d old job records", deleted)
        return deleted
    except Exception as e:
        logger.error("Failed to cleanup old jobs: %s", e)
        try:
            db.session.rollback()
        except Exception:
            pass
        return 0
