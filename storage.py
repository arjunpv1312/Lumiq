"""
storage.py — Unified file storage abstraction for Lumiq.

Provides a consistent interface for reading and writing files
regardless of the underlying backend (local disk or AWS S3).

Usage:
    from storage import get_storage
    store = get_storage()

    # Save a file
    key = store.save(local_path="/tmp/cleaned.csv", dest_key="outputs/job123/cleaned.csv")

    # Resolve a file path / presigned URL for download
    url_or_path = store.get_url(key)

    # Check existence
    exists = store.exists(key)

    # Delete
    store.delete(key)
"""

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Base interface ─────────────────────────────────────────────────────────────

class StorageBackend:
    """Abstract interface — subclasses must implement all methods."""

    def save(self, local_path: str, dest_key: str) -> str:
        """Copy/upload `local_path` to `dest_key`. Returns the canonical key."""
        raise NotImplementedError

    def get_url(self, key: str) -> str:
        """Return a URL or absolute path that can be used to serve the file."""
        raise NotImplementedError

    def get_local_path(self, key: str) -> str | None:
        """Return a local filesystem path for the key, or None if unavailable."""
        return None

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def delete(self, key: str) -> bool:
        raise NotImplementedError


# ── Local disk backend ─────────────────────────────────────────────────────────

class LocalStorage(StorageBackend):
    """
    Stores files on the local filesystem under BASE_DIR.
    Keys are relative paths (e.g. 'uploads/abc.csv', 'outputs/job/cleaned.csv').
    """

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)

    def _full_path(self, key: str) -> Path:
        return self.base_dir / key

    def save(self, local_path: str, dest_key: str) -> str:
        dest = self._full_path(dest_key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if str(dest) != local_path:
            shutil.copy2(local_path, dest)
        logger.debug("LocalStorage.save: %s → %s", local_path, dest)
        return dest_key

    def get_url(self, key: str) -> str:
        """Returns the absolute path on disk (used by send_file)."""
        return str(self._full_path(key))

    def get_local_path(self, key: str) -> str | None:
        path = self._full_path(key)
        return str(path) if path.exists() else None

    def exists(self, key: str) -> bool:
        return self._full_path(key).exists()

    def delete(self, key: str) -> bool:
        path = self._full_path(key)
        try:
            if path.exists():
                path.unlink()
                logger.debug("LocalStorage.delete: %s", path)
            return True
        except Exception as e:
            logger.error("LocalStorage.delete failed for %s: %s", key, e)
            return False


# ── AWS S3 backend ─────────────────────────────────────────────────────────────

class S3Storage(StorageBackend):
    """
    Stores files in an AWS S3 bucket.
    Keys map directly to S3 object keys within the configured bucket.
    """

    def __init__(self, bucket: str, region: str,
                 access_key: str, secret_key: str,
                 presigned_url_expiry: int = 3600):
        try:
            import boto3
            self._s3 = boto3.client(
                "s3",
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
        except ImportError:
            raise RuntimeError(
                "boto3 is required for S3 storage. "
                "Install it with: pip install boto3"
            )
        self.bucket = bucket
        self.expiry = presigned_url_expiry
        logger.info("S3Storage initialised — bucket: %s, region: %s", bucket, region)

    def save(self, local_path: str, dest_key: str) -> str:
        try:
            self._s3.upload_file(local_path, self.bucket, dest_key)
            logger.info("S3Storage.save: %s → s3://%s/%s", local_path, self.bucket, dest_key)
            return dest_key
        except Exception as e:
            logger.error("S3Storage.save failed: %s", e)
            raise

    def get_url(self, key: str) -> str:
        """Generate a presigned URL valid for `self.expiry` seconds."""
        try:
            url = self._s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=self.expiry,
            )
            return url
        except Exception as e:
            logger.error("S3Storage.get_url failed for %s: %s", key, e)
            raise

    def get_local_path(self, key: str) -> str | None:
        """S3 objects don't have a local path; return None."""
        return None

    def exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, key: str) -> bool:
        try:
            self._s3.delete_object(Bucket=self.bucket, Key=key)
            logger.debug("S3Storage.delete: s3://%s/%s", self.bucket, key)
            return True
        except Exception as e:
            logger.error("S3Storage.delete failed for %s: %s", key, e)
            return False


# ── Factory ────────────────────────────────────────────────────────────────────

_storage_instance: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """
    Return the configured storage backend (singleton).
    Reads USE_S3 and related settings from the environment / config.

    In development (USE_S3=false): returns LocalStorage rooted at BASE_DIR.
    In production (USE_S3=true):   returns S3Storage with configured bucket.
    """
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    from config import get_config
    cfg = get_config()

    if getattr(cfg, "USE_S3", False):
        _storage_instance = S3Storage(
            bucket=cfg.AWS_S3_BUCKET,
            region=cfg.AWS_S3_REGION,
            access_key=cfg.AWS_ACCESS_KEY_ID,
            secret_key=cfg.AWS_SECRET_ACCESS_KEY,
            presigned_url_expiry=cfg.AWS_S3_PRESIGNED_URL_EXPIRY,
        )
    else:
        _storage_instance = LocalStorage(base_dir=str(cfg.BASE_DIR))

    return _storage_instance


def reset_storage():
    """Reset the singleton — useful in tests."""
    global _storage_instance
    _storage_instance = None
