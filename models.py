"""
Database models for Lumiq application.
Provides persistent storage for job results and processing data.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from flask_sqlalchemy import SQLAlchemy


logger = logging.getLogger(__name__)
db = SQLAlchemy()


class JobResult(db.Model):
    """Store analysis results for each job."""
    
    __tablename__ = "job_results"
    
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(36), unique=True, nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(50), nullable=False, default="starting")
    progress = db.Column(db.Integer, default=0)
    data = db.Column(db.Text, nullable=True)  # JSON storage
    error = db.Column(db.Text, nullable=True)
    trace = db.Column(db.Text, nullable=True)  # Error traceback
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f"<JobResult {self.job_id}: {self.status}>"
    
    def set_data(self, data_dict):
        """Store data as JSON."""
        try:
            self.data = json.dumps(data_dict)
            db.session.commit()
            return True
        except Exception as e:
            logger.error("Failed to set data for job %s: %s", self.job_id, e)
            return False
    
    def get_data(self):
        """Retrieve data from JSON."""
        try:
            return json.loads(self.data) if self.data else {}
        except json.JSONDecodeError:
            logger.error("Failed to parse JSON data for job %s", self.job_id)
            return {}
    
    def to_dict(self):
        """Convert to dictionary for JSON responses."""
        return {
            "job_id": self.job_id,
            "filename": self.filename,
            "status": self.status,
            "progress": self.progress,
            "data": self.get_data(),
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class AuditLog(db.Model):
    """Track all security and operation events."""
    
    __tablename__ = "audit_logs"
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    event_type = db.Column(db.String(50), nullable=False, index=True)  # upload, download, error, security, etc.
    severity = db.Column(db.String(20), nullable=False, default="info")  # info, warning, error, critical
    user_ip = db.Column(db.String(45), nullable=True)
    job_id = db.Column(db.String(36), nullable=True, index=True)
    action = db.Column(db.String(255), nullable=False)
    details = db.Column(db.Text, nullable=True)
    status_code = db.Column(db.Integer, nullable=True)
    
    def __repr__(self):
        return f"<AuditLog {self.timestamp}: {self.event_type}>"
    
    @staticmethod
    def log_event(event_type, action, severity="info", user_ip=None, job_id=None, details=None, status_code=None):
        """Create and store an audit log entry."""
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
            db.session.commit()
            return True
        except Exception as e:
            logger.error("Failed to create audit log: %s", e)
            return False


def init_db(app):
    """Initialize database with Flask app."""
    db.init_app(app)
    
    with app.app_context():
        try:
            db.create_all()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize database: %s", e)
            raise


def store_result(job_id, data_dict):
    """Store or update job result in database."""
    try:
        result = JobResult.query.filter_by(job_id=job_id).first()
        
        if result:
            # Update existing record
            result.status = data_dict.get("status", result.status)
            result.progress = data_dict.get("pct", result.progress)
            result.error = data_dict.get("error", result.error)
            result.trace = data_dict.get("trace", result.trace)
            result.updated_at = datetime.utcnow()
            if data_dict.get("status") == "done":
                result.completed_at = datetime.utcnow()
            # Store full data
            result.set_data(data_dict)
        else:
            # Create new record
            result = JobResult(
                job_id=job_id,
                filename=data_dict.get("filename", "unknown"),
                status=data_dict.get("status", "starting"),
                progress=data_dict.get("pct", 0),
            )
            result.set_data(data_dict)
            db.session.add(result)
            db.session.commit()
        
        logger.debug("Result stored for job %s: %s", job_id, data_dict.get("status"))
        return True
    except Exception as e:
        logger.error("Failed to store result for job %s: %s", job_id, e)
        return False


def get_result(job_id):
    """Retrieve job result from database."""
    try:
        result = JobResult.query.filter_by(job_id=job_id).first()
        if result:
            data = result.get_data()
            data["status"] = result.status
            data["pct"] = result.progress
            if result.error:
                data["error"] = result.error
            if result.trace:
                data["trace"] = result.trace
            return data
        return None
    except Exception as e:
        logger.error("Failed to retrieve result for job %s: %s", job_id, e)
        return None


def cleanup_old_jobs(max_age_hours=2):
    """Delete job results older than max_age_hours."""
    try:
        from datetime import timedelta
        cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
        deleted = JobResult.query.filter(JobResult.completed_at < cutoff_time).delete()
        db.session.commit()
        logger.info("Cleaned up %d old job records", deleted)
        return deleted
    except Exception as e:
        logger.error("Failed to cleanup old jobs: %s", e)
        return 0
