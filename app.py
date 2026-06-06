from flask import (Flask, render_template, request,
                   redirect, url_for, session,
                   send_file, Response,
                   stream_with_context, jsonify)
import json
import logging
import os
import shutil
import threading
import time as _time
import uuid
from datetime import datetime
from pathlib import Path
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Import configuration and models
from config import get_config
from models import db, init_db, store_result as db_store_result, get_result as db_get_result, AuditLog

# Load configuration - FIXED: call get_config() function
config = get_config()

# Create Flask app with config
app = Flask(__name__)
app.config.from_object(config)

# If running in debug/development/testing mode, disable secure session cookies and strict CSRF for HTTP local testing
if app.config.get("DEBUG") or app.config.get("TESTING") or __name__ == "__main__":
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["WTF_CSRF_SSL_STRICT"] = False

# Initialize database
init_db(app)

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Initialize rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=config.RATELIMIT_DEFAULT.split(",") if isinstance(config.RATELIMIT_DEFAULT, str) else ["200 per day", "50 per hour"],
    storage_uri=config.RATELIMIT_STORAGE_URL,
)

# Setup logging
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

# Create required directories
Path(config.UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)
Path(config.OUTPUT_FOLDER).mkdir(parents=True, exist_ok=True)
Path(config.DATABASE_FOLDER).mkdir(parents=True, exist_ok=True)
# ── Wrapper functions for database operations ────────────
def store_result(job_id, data_dict):
    """Store job result in database."""
    with app.app_context():
        db_store_result(job_id, data_dict)


def get_result(job_id):
    """Retrieve job result from database."""
    with app.app_context():
        return db_get_result(job_id)


# ── Request logging and middleware ─────────────────────
@app.before_request
def log_request():
    """Log incoming request details."""
    request.start_time = _time.time()
    logger.info(
        "Request: %s %s from %s",
        request.method,
        request.path,
        request.remote_addr
    )
    request.request_id = str(uuid.uuid4())


@app.after_request
def log_response(response):
    """Log response details."""
    duration = _time.time() - getattr(request, "start_time", _time.time())
    logger.info(
        "Response: %s %s - Status: %d - Duration: %.2fs",
        request.method,
        request.path,
        response.status_code,
        duration
    )
    return response



def allowed_file(filename):
    return (
        isinstance(filename, str)
        and "." in filename
        and filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS
    )


def validate_file_size(file):
    """Validate file size before processing."""
    try:
        if not file or not file.filename:
            return False, "No file provided"
        
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > config.MAX_FILE_SIZE:
            return False, f"File exceeds {config.MAX_FILE_SIZE // (1024*1024)}MB limit"
        if file_size == 0:
            return False, "File is empty"
        return True, None
    except Exception as e:
        logger.error("File size validation error: %s", e)
        return False, "Invalid file"


def validate_input(text, max_length=None):
    """Validate text input."""
    if max_length is None:
        max_length = config.MAX_PREDICTION_LENGTH
    
    if not text or not isinstance(text, str):
        return False, "Invalid input"
    
    if len(text) == 0:
        return False, "Input is empty"
    
    if len(text) > max_length:
        return False, f"Input exceeds {max_length} character limit"
    
    return True, None


def validate_job_id(job_id):
    """Validate job ID format."""
    try:
        uuid.UUID(job_id)
        return True
    except (ValueError, AttributeError):
        return False


@app.after_request
def add_security_headers(response):
    """Add security headers to all responses."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net cdn.plot.ly; "
        "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
        "img-src 'self' data: https:; "
        "font-src 'self' cdn.jsdelivr.net; "
        "connect-src 'self'; "
        "frame-ancestors 'self';"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "geolocation=(), "
        "microphone=(), "
        "camera=(), "
        "payment=()"
    )
    return response


# ── Comprehensive Error Handlers ───────────────────────
@app.errorhandler(400)
def bad_request(error):
    """Handle bad request errors."""
    logger.warning("Bad request from %s: %s", request.remote_addr, str(error))
    AuditLog.log_event(
        "request_error",
        "Bad request",
        "warning",
        request.remote_addr,
        status_code=400
    )
    return jsonify({"error": "Bad request", "message": str(error)}), 400


@app.errorhandler(403)
def forbidden(error):
    """Handle forbidden errors."""
    logger.warning("Forbidden access from %s: %s", request.remote_addr, str(error))
    AuditLog.log_event(
        "security",
        "Forbidden access attempt",
        "warning",
        request.remote_addr,
        status_code=403
    )
    return jsonify({"error": "Forbidden"}), 403


@app.errorhandler(404)
def not_found(error):
    """Handle not found errors."""
    logger.debug("Not found: %s from %s", request.path, request.remote_addr)
    return jsonify({"error": "Resource not found"}), 404


@app.errorhandler(405)
def method_not_allowed(error):
    """Handle method not allowed errors."""
    logger.warning("Method not allowed: %s %s from %s", request.method, request.path, request.remote_addr)
    return jsonify({"error": "Method not allowed"}), 405


@app.errorhandler(413)
def too_large(error):
    """Handle file too large error."""
    logger.warning("File too large from %s", request.remote_addr)
    AuditLog.log_event(
        "upload_error",
        "File exceeds size limit",
        "warning",
        request.remote_addr,
        status_code=413
    )
    return jsonify({"error": "File too large"}), 413


@app.errorhandler(429)
def ratelimit_handler(error):
    """Handle rate limit exceeded."""
    logger.warning("Rate limit exceeded for %s: %s", request.remote_addr, request.path)
    AuditLog.log_event(
        "rate_limit",
        f"Rate limit exceeded on {request.path}",
        "warning",
        request.remote_addr,
        status_code=429
    )
    return jsonify({"error": "Too many requests", "message": "Rate limit exceeded"}), 429


@app.errorhandler(500)
def internal_error(error):
    """Handle internal server errors."""
    logger.error("Internal server error: %s", str(error), exc_info=True)
    AuditLog.log_event(
        "server_error",
        "Internal server error",
        "critical",
        request.remote_addr,
        status_code=500
    )
    return jsonify({
        "error": "Internal server error",
        "message": "An unexpected error occurred"
    }), 500


@app.errorhandler(Exception)
def handle_exception(error):
    """Handle uncaught exceptions."""
    if isinstance(error, HTTPException):
        return error
    
    logger.error("Uncaught exception: %s", str(error), exc_info=True)
    AuditLog.log_event(
        "server_error",
        f"Uncaught exception: {type(error).__name__}",
        "critical",
        request.remote_addr
    )
    
    if config.DEBUG:
        return jsonify({
            "error": "Internal server error",
            "message": str(error),
            "type": type(error).__name__
        }), 500
    else:
        return jsonify({
            "error": "Internal server error",
            "message": "An unexpected error occurred"
        }), 500


def _get_session_job():
    """Get job information from session."""
    return (
        session.get("job_id"),
        session.get("filepath"),
        session.get("filename"),
    )


def _send_download(path, download_name):
    """Send file download or redirect if file missing."""
    if path and os.path.exists(path):
        return send_file(path, as_attachment=True,
                         download_name=download_name)
    logger.warning("Download file not found: %s", path)
    return redirect(url_for("index"))


def _cleanup_old_files(max_age_hours=None):
    """Clean up old job files from disk."""
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
                # Skip system files
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


# ── Routes ─────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
@limiter.limit("5 per minute")
def upload():
    """Upload and process CSV file with security checks."""
    job_id = str(uuid.uuid4())
    user_ip = request.remote_addr
    
    try:
        if "file" not in request.files:
            logger.warning("Upload attempt without file from %s", user_ip)
            AuditLog.log_event("upload_error", "Missing file", "warning", user_ip)
            return redirect(url_for("index"))

        file = request.files["file"]
        
        # Validate filename
        if not file.filename or not allowed_file(file.filename):
            logger.warning("Invalid filename: %s from %s", file.filename, user_ip)
            AuditLog.log_event("upload_error", f"Invalid filename: {file.filename}", "warning", user_ip)
            return redirect(url_for("index"))

        # Validate file size
        is_valid, error_msg = validate_file_size(file)
        if not is_valid:
            logger.warning("File validation failed: %s from %s", error_msg, user_ip)
            AuditLog.log_event("upload_error", error_msg, "warning", user_ip)
            return redirect(url_for("index"))

        # Sanitize and save file
        filename = secure_filename(file.filename)
        filepath = os.path.join(config.UPLOAD_FOLDER, job_id + "_" + filename)
        file.save(filepath)
        
        # Store in session
        session["job_id"] = job_id
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
    """Load sample dataset."""
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
        shutil.copy2(src, filepath)
        
        session["job_id"] = job_id
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
        job_id=session.get("job_id"))

def run_job(job_id, filepath, filename):
    with app.app_context():
        _run_job_impl(job_id, filepath, filename)

def _run_job_impl(job_id, filepath, filename):
    try:
        # Clean up old files at start
        _cleanup_old_files(max_age_hours=config.JOB_CLEANUP_AGE_HOURS)

        from modules.cleaner       import clean_data
        from modules.eda           import run_eda
        from modules.sentiment     import run_sentiment
        from modules.dashboard     import run_dashboard
        from modules.wordcloud_gen import generate_wordclouds
        from modules.insights      import generate_insights
        from modules.pdf_report    import generate_pdf
        from modules.topic_model   import extract_topics
        from modules.excel_export  import generate_excel

        logger.info("Job %s: Starting pipeline", job_id)
        
        store_result(job_id,
                     {"status":"cleaning","pct":8})
        df, clean_path, clean_meta = clean_data(filepath)

        store_result(job_id,
                     {"status":"eda","pct":20})
        eda_stats = run_eda(df, clean_meta)

        store_result(job_id,
                     {"status":"sentiment","pct":40})
        sentiment_stats = run_sentiment(df)

        # Add sentiment labels to df for downstream dashboard modules
        if sentiment_stats.get("available") and "text_column" in sentiment_stats:
            text_col = sentiment_stats["text_column"]
            from modules.sentiment import clean_series, vader_batch, detect_ground_truth
            df["clean_text"] = clean_series(df[text_col])
            df["vader_label"] = vader_batch(df["clean_text"].tolist())
            
            # Detect ground truth labels
            gt_col, gt_type = detect_ground_truth(df)
            if gt_col:
                if gt_type == "rating":
                    def rating_to_sentiment(r):
                        try:
                            val = float(r)
                            if val >= 4.0: return "Positive"
                            elif val <= 2.0: return "Negative"
                            else: return "Neutral"
                        except Exception:
                            return "Neutral"
                    df["target_label"] = df[gt_col].apply(rating_to_sentiment)
                else:
                    def standardize_sentiment(s):
                        s_str = str(s).strip().lower()
                        if s_str in ["positive", "pos", "1", "2", "4", "5", "good"]: return "Positive"
                        elif s_str in ["negative", "neg", "0", "bad"]: return "Negative"
                        else: return "Neutral"
                    df["target_label"] = df[gt_col].apply(standardize_sentiment)
            else:
                df["target_label"] = df["vader_label"]

        store_result(job_id,
                     {"status":"topics","pct":60})
        text_col = sentiment_stats.get("text_column")
        if text_col and text_col in df.columns:
            texts      = df[text_col].dropna().tolist()
            topic_data = extract_topics(texts)
        else:
            topic_data = {"available": False}

        store_result(job_id,
                     {"status":"dashboard","pct":70})
        dashboard_charts = run_dashboard(
            df, sentiment_stats)

        store_result(job_id,
                     {"status":"wordcloud","pct":78})
        wc_paths = generate_wordclouds(sentiment_stats)

        store_result(job_id,
                     {"status":"insights","pct":84})
        insights = generate_insights(
            eda_stats, sentiment_stats)

        store_result(job_id,
                     {"status":"excel","pct":90})
        excel_path = generate_excel(
            filename, clean_path,
            eda_stats, sentiment_stats, insights)

        store_result(job_id,
                     {"status":"pdf","pct":95})
        pdf_path = generate_pdf(
            filename, eda_stats,
            sentiment_stats, insights)

        store_result(job_id, {
            "status":           "done",
            "pct":              100,
            "clean_path":       clean_path,
            "eda_stats":        eda_stats,
            "sentiment_stats":  sentiment_stats,
            "dashboard_charts": dashboard_charts,
            "wc_paths":         wc_paths,
            "insights":         insights,
            "topic_data":       topic_data,
            "pdf_path":         pdf_path,
            "excel_path":       excel_path,
            "sample_note":      clean_meta.get(
                                    "sample_note",""),
            "was_sampled":      clean_meta.get(
                                    "was_sampled",False),
        })
        
        logger.info("Job %s: Pipeline completed successfully", job_id)

    except Exception as e:
        import traceback
        logger.error("Job %s failed: %s", job_id, str(e), exc_info=True)
        AuditLog.log_event(
            "job_error",
            f"Job processing failed: {str(e)}",
            "error",
            job_id=job_id
        )
        store_result(job_id, {
            "status": "error",
            "error":  str(e),
            "trace":  traceback.format_exc(),
            "pct":    0,
        })

@app.route("/start_process")
@limiter.limit("10 per minute")
def start_process():
    """Start background processing job."""
    user_ip = request.remote_addr
    job_id = session.get("job_id")
    filepath = session.get("filepath")
    filename = session.get("filename", "data.csv")
    
    try:
        # Validate job ID
        if not job_id or not validate_job_id(job_id):
            logger.warning("Invalid job ID from %s: %s", user_ip, job_id)
            AuditLog.log_event("process_error", "Invalid job ID", "warning", user_ip)
            return jsonify({"error": "invalid job"}), 400
        
        # Validate filepath
        if not filepath or not os.path.exists(filepath):
            logger.error("File not found for job %s: %s from %s", job_id, filepath, user_ip)
            AuditLog.log_event("process_error", "File missing", "error", user_ip, job_id)
            return jsonify({"error": "file missing"}), 400
        
        # Initialize job in database
        store_result(job_id, {
            "status": "starting",
            "pct": 5,
            "filename": filename,
        })
        
        # Start background thread
        t = threading.Thread(
            target=run_job,
            args=(job_id, filepath, filename),
            daemon=True)
        t.start()
        
        logger.info("Processing started (job_id: %s) from %s", job_id, user_ip)
        AuditLog.log_event("process", "Processing started", "info", user_ip, job_id)
        
        return jsonify({"started": True})
        
    except Exception as e:
        logger.error("Start process error for job %s: %s", job_id, str(e), exc_info=True)
        AuditLog.log_event("process_error", f"Failed to start process: {str(e)}", "error", user_ip, job_id)
        return jsonify({"error": "processing failed"}), 500

# ── SSE progress ───────────────────────────────────────────
@app.route("/progress/<job_id>")
@limiter.limit("100 per minute")
def progress(job_id):
    """Stream processing progress via SSE."""
    user_ip = request.remote_addr
    
    try:
        # Validate job ID
        if not job_id or not validate_job_id(job_id):
            logger.warning("Invalid job ID for progress from %s: %s", user_ip, job_id)
            return jsonify({"error": "invalid job"}), 400
        
        def generate():
            try:
                while True:
                    result = get_result(job_id) or {}
                    # Filter out large data fields for streaming
                    safe = {k: v for k, v in result.items()
                            if k not in (
                                "eda_stats","sentiment_stats",
                                "dashboard_charts","insights",
                                "topic_data")}
                    yield f"data: {json.dumps(safe)}\n\n"
                    if result.get("status") in ("done","error"):
                        break
                    _time.sleep(0.8)
            except Exception as e:
                logger.error("Error during progress streaming for job %s: %s", job_id, e)
                yield f"data: {json.dumps({'error': 'stream interrupted'})}\n\n"
        
        logger.debug("Progress streaming started (job_id: %s) from %s", job_id, user_ip)
        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control":"no-cache",
                     "X-Accel-Buffering":"no"})
                     
    except Exception as e:
        logger.error("Progress route error for job %s: %s", job_id, e, exc_info=True)
        return jsonify({"error": "stream failed"}), 500


@app.route("/results")
@limiter.limit("20 per minute")
def results():
    """Display analysis results."""
    user_ip = request.remote_addr
    job_id = session.get("job_id")
    
    try:
        if not job_id:
            logger.warning("Results requested without job_id from %s", user_ip)
            return redirect(url_for("index"))
        
        data = get_result(job_id) or {}
        if data.get("status") != "done":
            logger.debug("Results requested but job not done (job_id: %s) from %s", job_id, user_ip)
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

# ── Live predictor ─────────────────────────────────────────
@app.route("/predict", methods=["POST"])
@limiter.limit("30 per minute")
def predict():
    """Live sentiment prediction."""
    user_ip = request.remote_addr
    
    try:
        from modules.sentiment import predict_live
        
        # Validate input
        text = request.json.get("text", "") if request.json else ""
        is_valid, error_msg = validate_input(text)
        
        if not is_valid:
            logger.warning("Invalid prediction input from %s: %s", user_ip, error_msg)
            AuditLog.log_event("predict_error", error_msg, "warning", user_ip)
            return jsonify({"error": error_msg}), 400
        
        # Perform prediction
        result = predict_live(text)
        
        logger.debug("Prediction completed from %s", user_ip)
        AuditLog.log_event("predict", "Prediction performed", "info", user_ip)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error("Prediction error from %s: %s", user_ip, str(e), exc_info=True)
        AuditLog.log_event("predict_error", f"Prediction failed: {str(e)}", "error", user_ip)
        return jsonify({"error": "Prediction failed"}), 500


# ── Downloads ──────────────────────────────────────────────
@app.route("/download/csv")
@limiter.limit("20 per minute")
def download_csv():
    """Download cleaned CSV file."""
    user_ip = request.remote_addr
    job_id, _, _ = _get_session_job()
    
    try:
        if not job_id:
            logger.warning("CSV download without job_id from %s", user_ip)
            return redirect(url_for("index"))
        
        data = get_result(job_id) or {}
        path = data.get("clean_path")
        
        logger.info("CSV download (job_id: %s) from %s", job_id, user_ip)
        AuditLog.log_event("download", "CSV downloaded", "info", user_ip, job_id)
        
        return _send_download(path, "lumiq_cleaned.csv")
        
    except Exception as e:
        logger.error("CSV download error from %s: %s", user_ip, e, exc_info=True)
        AuditLog.log_event("download_error", f"CSV download failed: {str(e)}", "error", user_ip, job_id)
        return redirect(url_for("index"))


@app.route("/download/excel")
@limiter.limit("20 per minute")
def download_excel():
    """Download Excel report."""
    user_ip = request.remote_addr
    job_id, _, _ = _get_session_job()
    
    try:
        if not job_id:
            logger.warning("Excel download without job_id from %s", user_ip)
            return redirect(url_for("index"))
        
        data = get_result(job_id) or {}
        path = data.get("excel_path")
        
        logger.info("Excel download (job_id: %s) from %s", job_id, user_ip)
        AuditLog.log_event("download", "Excel downloaded", "info", user_ip, job_id)
        
        return _send_download(path, "lumiq_report.xlsx")
        
    except Exception as e:
        logger.error("Excel download error from %s: %s", user_ip, e, exc_info=True)
        AuditLog.log_event("download_error", f"Excel download failed: {str(e)}", "error", user_ip, job_id)
        return redirect(url_for("index"))


@app.route("/download/pdf")
@limiter.limit("20 per minute")
def download_pdf():
    """Download PDF report."""
    user_ip = request.remote_addr
    job_id, _, _ = _get_session_job()
    
    try:
        if not job_id:
            logger.warning("PDF download without job_id from %s", user_ip)
            return redirect(url_for("index"))
        
        data = get_result(job_id) or {}
        path = data.get("pdf_path")
        
        logger.info("PDF download (job_id: %s) from %s", job_id, user_ip)
        AuditLog.log_event("download", "PDF downloaded", "info", user_ip, job_id)
        
        return _send_download(path, "lumiq_report.pdf")
        
    except Exception as e:
        logger.error("PDF download error from %s: %s", user_ip, e, exc_info=True)
        AuditLog.log_event("download_error", f"PDF download failed: {str(e)}", "error", user_ip, job_id)
        return redirect(url_for("index"))


@app.route("/cleanup")
@limiter.limit("5 per hour")
def cleanup_route():
    """Clean up old job files and database records."""
    user_ip = request.remote_addr
    
    try:
        # Clean database
        from models import cleanup_old_jobs
        db_deleted = cleanup_old_jobs(config.JOB_CLEANUP_AGE_HOURS)
        
        # Clean filesystem
        fs_deleted = _cleanup_old_files(config.JOB_CLEANUP_AGE_HOURS)
        
        logger.info("Cleanup completed: %d DB records, %d files from %s", 
                   db_deleted, fs_deleted, user_ip)
        AuditLog.log_event("cleanup", f"Cleaned {db_deleted} DB records, {fs_deleted} files", "info", user_ip)
        
        return jsonify({"db_deleted": db_deleted, "fs_deleted": fs_deleted})
        
    except Exception as e:
        logger.error("Cleanup error from %s: %s", user_ip, e, exc_info=True)
        AuditLog.log_event("cleanup_error", f"Cleanup failed: {str(e)}", "error", user_ip)
        return jsonify({"error": "Cleanup failed"}), 500

if __name__ == "__main__":
    app.run(debug=True, threaded=True,
            use_reloader=False)