"""
Configuration management for Lumiq application.
Loads settings from environment variables and .env file.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Base configuration class."""

    # ── Directory settings ────────────────────────────────────────────────────
    BASE_DIR = Path(__file__).resolve().parent
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    OUTPUT_FOLDER = os.path.join(BASE_DIR, "static", "outputs")
    DATABASE_FOLDER = os.path.join(BASE_DIR, "data")

    # ── Flask settings ────────────────────────────────────────────────────────
    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    DEBUG = os.getenv("FLASK_DEBUG", "True").lower() in ("true", "1")
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "lumiq_secret_2024_change_in_production")

    # ── Session settings ──────────────────────────────────────────────────────
    PERMANENT_SESSION_LIFETIME = int(os.getenv("PERMANENT_SESSION_LIFETIME", "3600"))
    SESSION_REFRESH_EACH_REQUEST = os.getenv("SESSION_REFRESH_EACH_REQUEST", "True").lower() in ("true", "1")
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "True").lower() in ("true", "1")
    SESSION_COOKIE_HTTPONLY = os.getenv("SESSION_COOKIE_HTTPONLY", "True").lower() in ("true", "1")
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")

    # ── CSRF settings ─────────────────────────────────────────────────────────
    WTF_CSRF_TIME_LIMIT = None
    WTF_CSRF_SSL_STRICT = os.getenv("WTF_CSRF_SSL_STRICT", "True").lower() in ("true", "1")

    # ── File upload settings ──────────────────────────────────────────────────
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(20 * 1024 * 1024)))  # 20 MB
    MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(50 * 1024 * 1024)))            # 50 MB
    ALLOWED_EXTENSIONS = {"csv"}

    # ── Rate limiting settings ────────────────────────────────────────────────
    RATELIMIT_STORAGE_URL = os.getenv("RATELIMIT_STORAGE_URL", "redis://localhost:6379/2")
    RATELIMIT_DEFAULT = os.getenv("RATELIMIT_DEFAULT", "200 per day, 50 per hour")
    RATELIMIT_UPLOAD = os.getenv("RATELIMIT_UPLOAD", "5 per minute")
    RATELIMIT_SAMPLE = os.getenv("RATELIMIT_SAMPLE", "10 per minute")
    RATELIMIT_PROCESS = os.getenv("RATELIMIT_PROCESS", "10 per minute")
    RATELIMIT_PROGRESS = os.getenv("RATELIMIT_PROGRESS", "100 per minute")
    RATELIMIT_RESULTS = os.getenv("RATELIMIT_RESULTS", "20 per minute")
    RATELIMIT_PREDICT = os.getenv("RATELIMIT_PREDICT", "30 per minute")
    RATELIMIT_DOWNLOAD = os.getenv("RATELIMIT_DOWNLOAD", "20 per minute")
    RATELIMIT_CLEANUP = os.getenv("RATELIMIT_CLEANUP", "5 per hour")

    # ── Database (PostgreSQL / SQLite) ────────────────────────────────────────
    _db_url = os.getenv("DATABASE_URL", "")
    # Normalise relative sqlite:/// paths → absolute so SQLite can create the file
    if not _db_url:
        _db_url = f"sqlite:///{os.path.join(DATABASE_FOLDER, 'lumiq.db')}"
    elif _db_url.startswith("sqlite:///."):
        # e.g. sqlite:///./data/lumiq.db → sqlite:////absolute/path/data/lumiq.db
        _rel = _db_url[len("sqlite:///"):]
        _db_url = "sqlite:///" + str(Path(BASE_DIR) / _rel)
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Connection pool settings — critical for PostgreSQL under concurrent load
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "300")),  # recycle every 5 min
        "pool_pre_ping": True,   # verify connection health before checkout
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
    }

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # ── Celery ────────────────────────────────────────────────────────────────
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
    CELERY_TASK_SERIALIZER = "json"
    CELERY_RESULT_SERIALIZER = "json"
    CELERY_ACCEPT_CONTENT = ["json"]
    CELERY_RESULT_EXPIRES = int(os.getenv("CELERY_RESULT_EXPIRES", "3600"))  # 1 hour
    CELERY_TASK_TRACK_STARTED = True
    CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # one task at a time per worker slot
    CELERY_TASK_ACKS_LATE = True           # ack after completion, not on receipt

    # ── Flask-SocketIO ────────────────────────────────────────────────────────
    SOCKETIO_ASYNC_MODE = os.getenv("SOCKETIO_ASYNC_MODE", "gevent")
    # Empty string → None so SocketIO runs in-process (dev without Redis)
    _mq_raw = os.getenv(
        "SOCKETIO_MESSAGE_QUEUE",
        os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )
    SOCKETIO_MESSAGE_QUEUE = _mq_raw if _mq_raw else None

    # ── AWS S3 File Storage ───────────────────────────────────────────────────
    USE_S3 = os.getenv("USE_S3", "false").lower() in ("true", "1")
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET", "lumiq-storage")
    AWS_S3_REGION = os.getenv("AWS_S3_REGION", "us-east-1")
    AWS_S3_PRESIGNED_URL_EXPIRY = int(os.getenv("AWS_S3_PRESIGNED_URL_EXPIRY", "3600"))

    # ── Logging settings ──────────────────────────────────────────────────────
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", os.path.join(BASE_DIR, "logs", "lumiq.log"))
    LOG_FORMAT = os.getenv(
        "LOG_FORMAT",
        "%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s"
    )

    # ── Processing settings ───────────────────────────────────────────────────
    JOB_CLEANUP_AGE_HOURS = int(os.getenv("JOB_CLEANUP_AGE_HOURS", "2"))
    MAX_PREDICTION_LENGTH = int(os.getenv("MAX_PREDICTION_LENGTH", "5000"))
    CELERY_WORKER_CONCURRENCY = int(os.getenv("CELERY_WORKER_CONCURRENCY", "2"))

    # ── Security settings ─────────────────────────────────────────────────────
    ENABLE_CORS = os.getenv("ENABLE_CORS", "False").lower() in ("true", "1")
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
    TRUSTED_PROXIES = os.getenv("TRUSTED_PROXIES", "127.0.0.1").split(",")


class DevelopmentConfig(Config):
    """Development configuration — relaxed security, verbose logs."""
    DEBUG = True
    TESTING = False
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_SSL_STRICT = False
    # Use in-memory rate limiting; no Redis required in dev
    RATELIMIT_STORAGE_URL = os.getenv("RATELIMIT_STORAGE_URL", "memory://")
    # SQLite doesn't support pool_size/max_overflow — only pre_ping is safe
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    def __init__(self):
        super().__init__()
        # Ensure the SQLite data directory exists before the engine connects
        import pathlib
        if "sqlite" in self.SQLALCHEMY_DATABASE_URI:
            # Extract path from sqlite:////abs/path or sqlite:///rel
            uri = self.SQLALCHEMY_DATABASE_URI
            db_path = uri.replace("sqlite:///", "")
            pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)


class ProductionConfig(Config):
    """Production configuration — strict security, PG pool, Redis rate-limit."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True


class TestingConfig(Config):
    """Testing configuration — in-memory SQLite, CSRF disabled."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    CELERY_TASK_ALWAYS_EAGER = True   # run tasks synchronously in tests
    CELERY_TASK_EAGER_PROPAGATES = True
    SOCKETIO_ASYNC_MODE = "threading"
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}


def get_config():
    """Get configuration based on FLASK_ENV."""
    env = os.getenv("FLASK_ENV", "development")
    if env == "development":
        return DevelopmentConfig()
    elif env == "testing":
        return TestingConfig()
    else:
        return ProductionConfig()
