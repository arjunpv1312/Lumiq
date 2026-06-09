"""
app.py — Lumiq Flask application.

Phase 1 changes:
  - Python threading replaced by Celery task dispatch (tasks.run_pipeline)
  - SSE progress endpoint replaced by Flask-SocketIO WebSocket push
  - Flask-Migrate added for schema version control
  - Storage backend abstraction wired into download routes
"""

from flask import (Flask, render_template, request,
                   redirect, url_for, session,
                   send_file, Response,
                   stream_with_context, jsonify)
from flask_migrate import Migrate
from flask_socketio import SocketIO, join_room, leave_room
import json
import logging
import os
import shutil
import time as _time
import uuid
from datetime import datetime
from pathlib import Path
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# ── Config & Models ───────────────────────────────────────────────────────────
from config import get_config
from models import db, init_db, store_result as db_store_result, get_result as db_get_result, AuditLog

config = get_config()

# ── Flask app factory ─────────────────────────────────────────────────────────
app = Flask(__name__)
app.config.from_object(config)

# Relax security for local HTTP dev/testing
if app.config.get("DEBUG") or app.config.get("TESTING") or __name__ == "__main__":
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["WTF_CSRF_SSL_STRICT"] = False

# ── Database ──────────────────────────────────────────────────────────────────
init_db(app)
migrate = Migrate(app, db)

# ── CSRF ──────────────────────────────────────────────────────────────────────
csrf = CSRFProtect(app)

# ── Rate Limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=(
        config.RATELIMIT_DEFAULT.split(",")
        if isinstance(config.RATELIMIT_DEFAULT, str)
        else ["200 per day", "50 per hour"]
    ),
    storage_uri=config.RATELIMIT_STORAGE_URL,
)

# ── Flask-SocketIO ─────────────────────────────────────────────────
# Auto-detect async mode: use gevent in production, threading in dev/Windows
_async_mode = config.SOCKETIO_ASYNC_MODE
if _async_mode == "gevent":
    try:
        import gevent  # noqa: F401
    except ImportError:
        _async_mode = "threading"

# message_queue ensures events emitted from Celery workers reach
# ALL Flask processes in a multi-process deployment.
# When None (dev), SocketIO uses in-process delivery.
socketio = SocketIO(
    app,
    async_mode=_async_mode,
    message_queue=config.SOCKETIO_MESSAGE_QUEUE,
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
)

# ── Logging ───────────────────────────────────────────────────────────────────
log_dir = Path(config.LOG_FILE).parent
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format=config.LOG_FORMAT,
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ── Ensure required directories exist ────────────────────────────────────────
Path(config.UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)
Path(config.OUTPUT_FOLDER).mkdir(parents=True, exist_ok=True)
Path(config.DATABASE_FOLDER).mkdir(parents=True, exist_ok=True)


# ── DB wrapper helpers ────────────────────────────────────────────────────────

def store_result(job_id: str, data_dict: dict) -> None:
    """Store job result — ensures we're inside an app context."""
    with app.app_context():
        db_store_result(job_id, data_dict)


def get_result(job_id: str) -> dict | None:
    """Retrieve job result — ensures we're inside an app context."""
    with app.app_context():
        return db_get_result(job_id)


# ── Request / Response middleware ─────────────────────────────────────────────

@app.before_request
def log_request():
    request.start_time = _time.time()
    request.request_id = str(uuid.uuid4())
    logger.info("Request: %s %s from %s", request.method, request.path, request.remote_addr)


@app.after_request
def log_response(response):
    duration = _time.time() - getattr(request, "start_time", _time.time())
    logger.info(
        "Response: %s %s — Status: %d — Duration: %.2fs",
        request.method, request.path, response.status_code, duration
    )
    return response


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net cdn.plot.ly cdn.socket.io; "
        "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
        "img-src 'self' data: https:; "
        "font-src 'self' cdn.jsdelivr.net; "
        "connect-src 'self' ws: wss:; "   # allow WebSocket connections
        "frame-ancestors 'self';"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "geolocation=(), microphone=(), camera=(), payment=()"
    )
    return response


# ── Input Validation Helpers ──────────────────────────────────────────────────

def allowed_file(filename: str) -> bool:
    return (
        isinstance(filename, str)
        and "." in filename
        and filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS
    )


def validate_file_size(file) -> tuple[bool, str | None]:
    try:
        if not file or not file.filename:
            return False, "No file provided"
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        if file_size > config.MAX_FILE_SIZE:
            return False, f"File exceeds {config.MAX_FILE_SIZE // (1024 * 1024)}MB limit"
        if file_size == 0:
            return False, "File is empty"
        return True, None
    except Exception as e:
        logger.error("File size validation error: %s", e)
        return False, "Invalid file"


def validate_input(text: str, max_length: int | None = None) -> tuple[bool, str | None]:
    if max_length is None:
        max_length = config.MAX_PREDICTION_LENGTH
    if not text or not isinstance(text, str):
        return False, "Invalid input"
    if len(text) == 0:
        return False, "Input is empty"
    if len(text) > max_length:
        return False, f"Input exceeds {max_length} character limit"
    return True, None


def validate_job_id(job_id: str) -> bool:
    try:
        uuid.UUID(job_id)
        return True
    except (ValueError, AttributeError):
        return False


# ── Error Handlers ────────────────────────────────────────────────────────────

@app.errorhandler(400)
def bad_request(error):
    logger.warning("Bad request from %s: %s", request.remote_addr, str(error))
    AuditLog.log_event("request_error", "Bad request", "warning", request.remote_addr, status_code=400)
    return jsonify({"error": "Bad request", "message": str(error)}), 400


@app.errorhandler(403)
def forbidden(error):
    logger.warning("Forbidden access from %s: %s", request.remote_addr, str(error))
    AuditLog.log_event("security", "Forbidden access attempt", "warning", request.remote_addr, status_code=403)
    return jsonify({"error": "Forbidden"}), 403


@app.errorhandler(404)
def not_found(error):
    logger.debug("Not found: %s from %s", request.path, request.remote_addr)
    return jsonify({"error": "Resource not found"}), 404


@app.errorhandler(405)
def method_not_allowed(error):
    logger.warning("Method not allowed: %s %s from %s", request.method, request.path, request.remote_addr)
    return jsonify({"error": "Method not allowed"}), 405


@app.errorhandler(413)
def too_large(error):
    logger.warning("File too large from %s", request.remote_addr)
    AuditLog.log_event("upload_error", "File exceeds size limit", "warning", request.remote_addr, status_code=413)
    return jsonify({"error": "File too large"}), 413


@app.errorhandler(429)
def ratelimit_handler(error):
    logger.warning("Rate limit exceeded for %s: %s", request.remote_addr, request.path)
    AuditLog.log_event("rate_limit", f"Rate limit exceeded on {request.path}", "warning",
                        request.remote_addr, status_code=429)
    return jsonify({"error": "Too many requests", "message": "Rate limit exceeded"}), 429


@app.errorhandler(500)
def internal_error(error):
    logger.error("Internal server error: %s", str(error), exc_info=True)
    AuditLog.log_event("server_error", "Internal server error", "critical",
                        request.remote_addr, status_code=500)
    return jsonify({"error": "Internal server error", "message": "An unexpected error occurred"}), 500


@app.errorhandler(Exception)
def handle_exception(error):
    if isinstance(error, HTTPException):
        return error
    logger.error("Uncaught exception: %s", str(error), exc_info=True)
    AuditLog.log_event("server_error", f"Uncaught exception: {type(error).__name__}", "critical",
                        request.remote_addr)
    if config.DEBUG:
        return jsonify({"error": "Internal server error", "message": str(error),
                        "type": type(error).__name__}), 500
    return jsonify({"error": "Internal server error", "message": "An unexpected error occurred"}), 500


# ── Session helpers ───────────────────────────────────────────────────────────

def _get_session_job() -> tuple[str | None, str | None, str | None]:
    return (
        session.get("job_id"),
        session.get("filepath"),
        session.get("filename"),
    )


def _send_download(path: str | None, download_name: str):
    """Serve a file download, handling both local paths and presigned S3 URLs."""
    if path is None:
        logger.warning("Download path is None for %s", download_name)
        return redirect(url_for("index"))

    # Presigned S3 URL — redirect the browser directly
    if path.startswith("http"):
        from flask import redirect as flask_redirect
        return flask_redirect(path)

    # Local path
    if os.path.exists(path):
        return send_file(path, as_attachment=True, download_name=download_name)

    logger.warning("Download file not found: %s", path)
    return redirect(url_for("index"))


def _cleanup_old_files(max_age_hours: int | None = None) -> int:
    """Delete old job artefacts from local disk."""
    if max_age_hours is None:
        max_age_hours = config.JOB_CLEANUP_AGE_HOURS
    now = _time.time()
    max_age = max_age_hours * 3600
    deleted = 0
    for folder in [config.UPLOAD_FOLDER, config.OUTPUT_FOLDER]:
        if not os.path.exists(folder):
            continue
        try:
            for fname in os.listdir(folder):
                if fname in ("sample_data.csv", "best_model.pkl") or fname == "cache":
                    continue
                fpath = os.path.join(folder, fname)
                if os.path.isfile(fpath):
                    age = now - os.path.getmtime(fpath)
                    if age > max_age:
                        try:
                            os.remove(fpath)
                            deleted += 1
                        except Exception as e:
                            logger.warning("Cleanup failed for %s: %s", fpath, e)
        except Exception as e:
            logger.error("Error during cleanup in %s: %s", folder, e)
    return deleted


# ── HTTP Routes ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
@limiter.limit("5 per minute")
def upload():
    """Upload and validate a CSV file, then redirect to loading screen."""
    job_id = str(uuid.uuid4())
    user_ip = request.remote_addr

    try:
        if "file" not in request.files:
            logger.warning("Upload attempt without file from %s", user_ip)
            AuditLog.log_event("upload_error", "Missing file", "warning", user_ip)
            return redirect(url_for("index"))

        file = request.files["file"]

        if not file.filename or not allowed_file(file.filename):
            logger.warning("Invalid filename: %s from %s", file.filename, user_ip)
            AuditLog.log_event("upload_error", f"Invalid filename: {file.filename}", "warning", user_ip)
            return redirect(url_for("index"))

        is_valid, error_msg = validate_file_size(file)
        if not is_valid:
            logger.warning("File validation failed: %s from %s", error_msg, user_ip)
            AuditLog.log_event("upload_error", error_msg, "warning", user_ip)
            return redirect(url_for("index"))

        filename = secure_filename(file.filename)
        filepath = os.path.join(config.UPLOAD_FOLDER, job_id + "_" + filename)
        file.save(filepath)

        session["job_id"]   = job_id
        session["filepath"] = filepath
        session["filename"] = filename

        logger.info("File uploaded: %s (job_id: %s, size: %s bytes) from %s",
                    filename, job_id, os.path.getsize(filepath), user_ip)
        AuditLog.log_event("upload", f"File uploaded: {filename}", "info", user_ip, job_id)

        return redirect(url_for("loading"))

    except Exception as e:
        logger.error("Upload error for job %s: %s", job_id, str(e), exc_info=True)
        AuditLog.log_event("upload_error", f"Upload failed: {str(e)}", "error", user_ip, job_id)
        return redirect(url_for("index"))


@app.route("/sample")
@limiter.limit("10 per minute")
def sample():
    """Load the built-in sample dataset."""
    job_id = str(uuid.uuid4())
    user_ip = request.remote_addr

    try:
        src = os.path.join(config.BASE_DIR, "static", "sample_data.csv")
        if not os.path.exists(src):
            logger.warning("Sample file not found from %s", user_ip)
            AuditLog.log_event("sample_error", "Sample file not found", "warning", user_ip)
            return redirect(url_for("index"))

        filename = "sample_reviews.csv"
        filepath = os.path.join(config.UPLOAD_FOLDER, job_id + "_" + filename)
        shutil.copy(src, filepath)

        session["job_id"]   = job_id
        session["filepath"] = filepath
        session["filename"] = filename

        logger.info("Sample loaded (job_id: %s) from %s", job_id, user_ip)
        AuditLog.log_event("sample", "Sample data loaded", "info", user_ip, job_id)

        return redirect(url_for("loading"))

    except Exception as e:
        logger.error("Sample load error for job %s: %s", job_id, str(e), exc_info=True)
        AuditLog.log_event("sample_error", f"Failed to load sample: {str(e)}", "error", user_ip, job_id)
        return redirect(url_for("index"))


@app.route("/loading")
def loading():
    return render_template(
        "loading.html",
        filename=session.get("filename"),
        job_id=session.get("job_id"),
    )


@app.route("/start_process")
@limiter.limit("10 per minute")
def start_process():
    """Validate the uploaded file and dispatch a Celery pipeline task."""
    user_ip  = request.remote_addr
    job_id   = session.get("job_id")
    filepath = session.get("filepath")
    filename = session.get("filename", "data.csv")

    try:
        if not job_id or not validate_job_id(job_id):
            logger.warning("Invalid job ID from %s: %s", user_ip, job_id)
            AuditLog.log_event("process_error", "Invalid job ID", "warning", user_ip)
            return jsonify({"error": "invalid job"}), 400

        if not filepath or not os.path.exists(filepath):
            logger.error("File not found for job %s from %s", job_id, user_ip)
            AuditLog.log_event("process_error", "File missing", "error", user_ip, job_id)
            return jsonify({"error": "file missing"}), 400

        # Initialise job record before dispatching
        db_store_result(job_id, {
            "status":   "queued",
            "pct":      2,
            "filename": filename,
        })

        # ── Dispatch to Celery (replaces threading.Thread) ────────────────────
        from tasks import run_pipeline
        task = run_pipeline.apply_async(
            args=[job_id, filepath, filename],
            task_id=None,         # let Celery generate a UUID task ID
            countdown=0,          # start immediately
        )

        # Persist the Celery task ID for later status lookups
        db_store_result(job_id, {
            "status":         "starting",
            "pct":            3,
            "celery_task_id": task.id,
            "filename":       filename,
        })

        logger.info("Pipeline dispatched — job_id=%s, task_id=%s from %s",
                    job_id, task.id, user_ip)
        AuditLog.log_event("process", "Pipeline dispatched", "info", user_ip, job_id)

        return jsonify({"started": True, "task_id": task.id})

    except Exception as e:
        logger.error("Start process error for job %s: %s", job_id, str(e), exc_info=True)
        AuditLog.log_event("process_error", f"Failed to start process: {str(e)}", "error", user_ip, job_id)
        return jsonify({"error": "processing failed"}), 500


# ── Legacy SSE progress endpoint (deprecated — kept as fallback) ──────────────
@app.route("/progress/<job_id>")
@limiter.limit("60 per minute")
def progress(job_id):
    """
    [DEPRECATED] SSE progress stream.

    Kept as a fallback for clients that do not support WebSockets.
    The primary progress mechanism is now the /jobs SocketIO namespace.
    """
    user_ip = request.remote_addr

    try:
        if not job_id or not validate_job_id(job_id):
            return jsonify({"error": "invalid job"}), 400

        def generate():
            try:
                while True:
                    result = get_result(job_id) or {}
                    safe = {k: v for k, v in result.items()
                            if k not in ("eda_stats", "sentiment_stats",
                                         "dashboard_charts", "insights", "topic_data")}
                    yield f"data: {json.dumps(safe)}\n\n"
                    if result.get("status") in ("done", "error"):
                        break
                    _time.sleep(1.0)
            except Exception as e:
                logger.error("SSE stream error for job %s: %s", job_id, e)
                yield f"data: {json.dumps({'error': 'stream interrupted'})}\n\n"

        logger.debug("SSE fallback stream started (job_id: %s) from %s", job_id, user_ip)
        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    except Exception as e:
        logger.error("Progress route error for job %s: %s", job_id, e, exc_info=True)
        return jsonify({"error": "stream failed"}), 500


@app.route("/results")
@limiter.limit("20 per minute")
def results():
    """Display analysis results."""
    user_ip = request.remote_addr
    job_id  = session.get("job_id")

    try:
        if not job_id:
            return redirect(url_for("index"))

        data = get_result(job_id) or {}
        if data.get("status") != "done":
            return redirect(url_for("loading"))

        logger.info("Results displayed (job_id: %s) from %s", job_id, user_ip)
        AuditLog.log_event("results", "Results viewed", "info", user_ip, job_id)

        return render_template(
            "results.html",
            filename         = session.get("filename"),
            eda_stats        = data.get("eda_stats",        {}),
            sentiment_stats  = data.get("sentiment_stats",  {}),
            dashboard_charts = data.get("dashboard_charts", {}),
            wc_paths         = data.get("wc_paths",         {}),
            insights         = data.get("insights",         []),
            topic_data       = data.get("topic_data",       {}),
            sample_note      = data.get("sample_note",      ""),
            was_sampled      = data.get("was_sampled",      False),
        )

    except Exception as e:
        logger.error("Results route error for job %s: %s", job_id, e, exc_info=True)
        AuditLog.log_event("results_error", f"Failed to display results: {str(e)}", "error", user_ip, job_id)
        return redirect(url_for("index"))


# ── Live Predictor ────────────────────────────────────────────────────────────

@app.route("/predict", methods=["POST"])
@limiter.limit("30 per minute")
def predict():
    """Live sentiment prediction endpoint."""
    user_ip = request.remote_addr

    try:
        from modules.sentiment import predict_live
        text = request.json.get("text", "") if request.json else ""
        is_valid, error_msg = validate_input(text)
        if not is_valid:
            AuditLog.log_event("predict_error", error_msg, "warning", user_ip)
            return jsonify({"error": error_msg}), 400

        result = predict_live(text)
        AuditLog.log_event("predict", "Prediction performed", "info", user_ip)
        return jsonify(result)

    except Exception as e:
        logger.error("Prediction error from %s: %s", user_ip, str(e), exc_info=True)
        AuditLog.log_event("predict_error", f"Prediction failed: {str(e)}", "error", user_ip)
        return jsonify({"error": "Prediction failed"}), 500


# ── Downloads ─────────────────────────────────────────────────────────────────

@app.route("/download/csv")
@limiter.limit("20 per minute")
def download_csv():
    user_ip = request.remote_addr
    job_id, _, _ = _get_session_job()
    try:
        if not job_id:
            return redirect(url_for("index"))
        data = get_result(job_id) or {}
        path = data.get("clean_path")
        AuditLog.log_event("download", "CSV downloaded", "info", user_ip, job_id)
        return _send_download(path, "lumiq_cleaned.csv")
    except Exception as e:
        logger.error("CSV download error from %s: %s", user_ip, e, exc_info=True)
        return redirect(url_for("index"))


@app.route("/download/excel")
@limiter.limit("20 per minute")
def download_excel():
    user_ip = request.remote_addr
    job_id, _, _ = _get_session_job()
    try:
        if not job_id:
            return redirect(url_for("index"))
        data = get_result(job_id) or {}
        path = data.get("excel_path")
        AuditLog.log_event("download", "Excel downloaded", "info", user_ip, job_id)
        return _send_download(path, "lumiq_report.xlsx")
    except Exception as e:
        logger.error("Excel download error from %s: %s", user_ip, e, exc_info=True)
        return redirect(url_for("index"))


@app.route("/download/pdf")
@limiter.limit("20 per minute")
def download_pdf():
    user_ip = request.remote_addr
    job_id, _, _ = _get_session_job()
    try:
        if not job_id:
            return redirect(url_for("index"))
        data = get_result(job_id) or {}
        path = data.get("pdf_path")
        AuditLog.log_event("download", "PDF downloaded", "info", user_ip, job_id)
        return _send_download(path, "lumiq_report.pdf")
    except Exception as e:
        logger.error("PDF download error from %s: %s", user_ip, e, exc_info=True)
        return redirect(url_for("index"))


@app.route("/cleanup")
@limiter.limit("5 per hour")
def cleanup_route():
    user_ip = request.remote_addr
    try:
        from models import cleanup_old_jobs
        db_deleted = cleanup_old_jobs(config.JOB_CLEANUP_AGE_HOURS)
        fs_deleted = _cleanup_old_files(config.JOB_CLEANUP_AGE_HOURS)
        logger.info("Cleanup: %d DB records, %d files from %s", db_deleted, fs_deleted, user_ip)
        AuditLog.log_event("cleanup", f"Cleaned {db_deleted} DB records, {fs_deleted} files", "info", user_ip)
        return jsonify({"db_deleted": db_deleted, "fs_deleted": fs_deleted})
    except Exception as e:
        logger.error("Cleanup error from %s: %s", user_ip, e, exc_info=True)
        return jsonify({"error": "Cleanup failed"}), 500


# ── WebSocket handlers (/jobs namespace) ──────────────────────────────────────

@socketio.on("connect", namespace="/jobs")
def ws_connect():
    logger.debug("WebSocket client connected: %s", request.sid)


@socketio.on("disconnect", namespace="/jobs")
def ws_disconnect():
    logger.debug("WebSocket client disconnected: %s", request.sid)


@socketio.on("subscribe_job", namespace="/jobs")
def ws_subscribe(data: dict):
    """
    Client sends: {"job_id": "<uuid>"}
    Server joins the client to a room named after the job_id.
    Celery tasks emit events to this room from tasks.py.
    """
    job_id = data.get("job_id", "")
    if not validate_job_id(job_id):
        logger.warning("Invalid job_id in subscribe_job: %s", job_id)
        return

    join_room(job_id)
    logger.debug("Client %s subscribed to job room %s", request.sid, job_id)

    # Send current status immediately so client doesn't wait for the next emit
    current = db_get_result(job_id)
    if current:
        safe = {k: v for k, v in current.items()
                if k not in ("eda_stats", "sentiment_stats",
                             "dashboard_charts", "insights", "topic_data")}
        socketio.emit("progress_update", safe, room=request.sid, namespace="/jobs")


@socketio.on("unsubscribe_job", namespace="/jobs")
def ws_unsubscribe(data: dict):
    job_id = data.get("job_id", "")
    if validate_job_id(job_id):
        leave_room(job_id)
        logger.debug("Client %s unsubscribed from job room %s", request.sid, job_id)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Use socketio.run() instead of app.run() so the WebSocket server starts
    socketio.run(
        app,
        debug=True,
        use_reloader=False,   # reloader conflicts with gevent
        port=5000,
        host="0.0.0.0",
    )