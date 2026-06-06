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
    
    # Directory settings
    BASE_DIR = Path(__file__).resolve().parent
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    OUTPUT_FOLDER = os.path.join(BASE_DIR, "static", "outputs")
    DATABASE_FOLDER = os.path.join(BASE_DIR, "data")
    
    # Flask settings
    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    DEBUG = os.getenv("FLASK_DEBUG", "True").lower() in ("true", "1")
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "lumiq_secret_2024_change_in_production")
    
    # Session settings
    PERMANENT_SESSION_LIFETIME = int(os.getenv("PERMANENT_SESSION_LIFETIME", "3600"))  # 1 hour
    SESSION_REFRESH_EACH_REQUEST = os.getenv("SESSION_REFRESH_EACH_REQUEST", "True").lower() in ("true", "1")
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "True").lower() in ("true", "1")
    SESSION_COOKIE_HTTPONLY = os.getenv("SESSION_COOKIE_HTTPONLY", "True").lower() in ("true", "1")
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    
    # CSRF settings
    WTF_CSRF_TIME_LIMIT = None  # No expiration for flexibility
    WTF_CSRF_SSL_STRICT = os.getenv("WTF_CSRF_SSL_STRICT", "True").lower() in ("true", "1")
    
    # File upload settings
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(20 * 1024 * 1024)))  # 20 MB
    MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(50 * 1024 * 1024)))  # 50 MB
    ALLOWED_EXTENSIONS = {"csv"}
    
    # Rate limiting settings
    RATELIMIT_STORAGE_URL = os.getenv("RATELIMIT_STORAGE_URL", "memory://")
    RATELIMIT_DEFAULT = os.getenv("RATELIMIT_DEFAULT", "200 per day, 50 per hour")
    RATELIMIT_UPLOAD = os.getenv("RATELIMIT_UPLOAD", "5 per minute")
    RATELIMIT_SAMPLE = os.getenv("RATELIMIT_SAMPLE", "10 per minute")
    RATELIMIT_PROCESS = os.getenv("RATELIMIT_PROCESS", "10 per minute")
    RATELIMIT_PROGRESS = os.getenv("RATELIMIT_PROGRESS", "100 per minute")
    RATELIMIT_RESULTS = os.getenv("RATELIMIT_RESULTS", "20 per minute")
    RATELIMIT_PREDICT = os.getenv("RATELIMIT_PREDICT", "30 per minute")
    RATELIMIT_DOWNLOAD = os.getenv("RATELIMIT_DOWNLOAD", "20 per minute")
    RATELIMIT_CLEANUP = os.getenv("RATELIMIT_CLEANUP", "5 per hour")
    
    # Database settings
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(DATABASE_FOLDER, 'lumiq.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Logging settings
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", os.path.join(BASE_DIR, "logs", "lumiq.log"))
    LOG_FORMAT = os.getenv(
        "LOG_FORMAT",
        "%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s"
    )
    
    # Processing settings
    JOB_CLEANUP_AGE_HOURS = int(os.getenv("JOB_CLEANUP_AGE_HOURS", "2"))
    MAX_PREDICTION_LENGTH = int(os.getenv("MAX_PREDICTION_LENGTH", "5000"))
    
    # Security settings
    ENABLE_CORS = os.getenv("ENABLE_CORS", "False").lower() in ("true", "1")
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
    TRUSTED_PROXIES = os.getenv("TRUSTED_PROXIES", "127.0.0.1").split(",")


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    TESTING = False
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_SSL_STRICT = False


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False


def get_config():
    """Get configuration based on FLASK_ENV."""
    env = os.getenv("FLASK_ENV", "development")
    if env == "development":
        return DevelopmentConfig()
    elif env == "testing":
        return TestingConfig()
    else:
        return ProductionConfig()
