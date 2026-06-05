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
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
OUTPUT_FOLDER = os.path.join(BASE_DIR, "static", "outputs")
ALLOWED_EXTENSIONS = {"csv"}
MAX_CONTENT_LENGTH = 20 * 1024 * 1024

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "lumiq_secret_2024")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

_results = {}
_lock = threading.Lock()


def store_result(k, v):
    with _lock:
        _results[k] = v


def get_result(k):
    with _lock:
        return _results.get(k)


def _get_session_job():
    return (
        session.get("job_id"),
        session.get("filepath"),
        session.get("filename"),
    )


def _send_download(path, download_name):
    if path and os.path.exists(path):
        return send_file(path, as_attachment=True,
                         download_name=download_name)
    return redirect(url_for("index"))


def allowed_file(filename):
    return (
        isinstance(filename, str)
        and "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )

# ── Auto cleanup old files ─────────────────────────────────
def cleanup_old_files(max_age_hours=2):
    now = _time.time()
    max_age = max_age_hours * 3600
    deleted = 0
    for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER]:
        if not os.path.exists(folder):
            continue
        for fname in os.listdir(folder):
            if fname in ("sample_data.csv",
                         "best_model.pkl"):
                continue
            if fname == "cache":
                continue
            fpath = os.path.join(folder, fname)
            if os.path.isfile(fpath):
                age = now - os.path.getmtime(fpath)
                if age > max_age:
                    try:
                        os.remove(fpath)
                        deleted += 1
                    except Exception:
                        pass
    return deleted

# ── Routes ─────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return redirect(url_for("index"))
    file = request.files["file"]
    if not file.filename or not allowed_file(file.filename):
        return redirect(url_for("index"))
    job_id   = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    filepath = os.path.join(
        UPLOAD_FOLDER, job_id + "_" + filename)
    file.save(filepath)
    session["job_id"]   = job_id
    session["filepath"] = filepath
    session["filename"] = filename
    return redirect(url_for("loading"))

@app.route("/sample")
def sample():
    src = os.path.join(BASE_DIR, "static", "sample_data.csv")
    if not os.path.exists(src):
        return redirect(url_for("index"))
    job_id = str(uuid.uuid4())
    filename = "sample_reviews.csv"
    filepath = os.path.join(UPLOAD_FOLDER, job_id + "_" + filename)
    shutil.copy2(src, filepath)
    session["job_id"] = job_id
    session["filepath"] = filepath
    session["filename"] = filename
    return redirect(url_for("loading"))

@app.route("/loading")
def loading():
    return render_template(
        "loading.html",
        filename=session.get("filename"),
        job_id=session.get("job_id"))

# ── Background job ─────────────────────────────────────────
def run_job(job_id, filepath, filename):
    try:
        cleanup_old_files(max_age_hours=2)

        from modules.cleaner       import clean_data
        from modules.eda           import run_eda
        from modules.sentiment     import run_sentiment
        from modules.dashboard     import run_dashboard
        from modules.wordcloud_gen import generate_wordclouds
        from modules.insights      import generate_insights
        from modules.pdf_report    import generate_pdf
        from modules.topic_model   import extract_topics
        from modules.excel_export  import generate_excel

        store_result(job_id,
                     {"status":"cleaning","pct":8})
        df, clean_path, clean_meta = clean_data(filepath)

        store_result(job_id,
                     {"status":"eda","pct":20})
        eda_stats = run_eda(df, clean_meta)

        store_result(job_id,
                     {"status":"sentiment","pct":40})
        sentiment_stats = run_sentiment(df)

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

    except Exception as e:
        import traceback
        store_result(job_id, {
            "status": "error",
            "error":  str(e),
            "trace":  traceback.format_exc(),
            "pct":    0,
        })

@app.route("/start_process")
def start_process():
    job_id   = session.get("job_id")
    filepath = session.get("filepath")
    filename = session.get("filename","data.csv")
    if not job_id or not filepath:
        return jsonify({"error":"no job"}), 400
    if not os.path.exists(filepath):
        return jsonify({"error":"file missing"}), 400
    store_result(job_id,
                 {"status":"starting","pct":5})
    t = threading.Thread(
        target=run_job,
        args=(job_id, filepath, filename),
        daemon=True)
    t.start()
    return jsonify({"started": True})

# ── SSE progress ───────────────────────────────────────────
@app.route("/progress/<job_id>")
def progress(job_id):
    def generate():
        while True:
            result = get_result(job_id) or {}
            safe   = {k: v for k, v in result.items()
                      if k not in (
                          "eda_stats","sentiment_stats",
                          "dashboard_charts","insights",
                          "topic_data")}
            yield f"data: {json.dumps(safe)}\n\n"
            if result.get("status") in ("done","error"):
                break
            _time.sleep(0.8)
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control":"no-cache",
                 "X-Accel-Buffering":"no"})

@app.route("/results")
def results():
    job_id = session.get("job_id")
    data   = get_result(job_id) or {}
    if data.get("status") != "done":
        return redirect(url_for("loading"))
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

# ── Live predictor ─────────────────────────────────────────
@app.route("/predict", methods=["POST"])
def predict():
    from modules.sentiment import predict_live
    text   = request.json.get("text","")
    result = predict_live(text)
    return jsonify(result)

# ── Downloads ──────────────────────────────────────────────
@app.route("/download/csv")
def download_csv():
    job_id, _, _ = _get_session_job()
    data = get_result(job_id) or {}
    return _send_download(data.get("clean_path"), "lumiq_cleaned.csv")

@app.route("/download/excel")
def download_excel():
    job_id, _, _ = _get_session_job()
    data = get_result(job_id) or {}
    return _send_download(data.get("excel_path"), "lumiq_report.xlsx")

@app.route("/download/pdf")
def download_pdf():
    job_id, _, _ = _get_session_job()
    data = get_result(job_id) or {}
    return _send_download(data.get("pdf_path"), "lumiq_report.pdf")

@app.route("/cleanup")
def cleanup_route():
    deleted = cleanup_old_files(max_age_hours=2)
    return jsonify({"deleted": deleted})

if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true",
        threaded=True,
        use_reloader=False,
    )