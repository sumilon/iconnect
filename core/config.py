"""
Application configuration.
Reads all settings from environment variables — no secrets hard-coded.
A `.env` file (local dev) or Cloud Run Secret Manager supplies the values.
"""

import os
import secrets


class Config:
    # ── Flask core ──────────────────────────────────────────────────────────
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

    # ── Session cookie hardening ────────────────────────────────────────────
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # True in production (Cloud Run is always HTTPS); False for local HTTP dev.
    SESSION_COOKIE_SECURE = (
        os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true"
    )

    # ── Upload limits ───────────────────────────────────────────────────────
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024          # 8 MB hard limit
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

    # ── Google Cloud ────────────────────────────────────────────────────────
    BUCKET_NAME      = os.environ.get("BUCKET_NAME", "your-bucket-name")
    FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY", "")


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False       # HTTP is fine locally


class ProductionConfig(Config):
    DEBUG = False


_config_map = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
}


def get_config():
    """Return the config class matching the FLASK_ENV environment variable."""
    env = os.environ.get("FLASK_ENV", "development").lower()
    return _config_map.get(env, DevelopmentConfig)