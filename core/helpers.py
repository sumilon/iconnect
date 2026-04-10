"""
Shared helpers: auth decorator, CSRF protection, rate limiting,
Firebase REST wrappers, Firestore utilities, and formatting functions.
"""

import os
import re
import secrets
import threading
from collections import defaultdict
from datetime import datetime, timezone
from functools import wraps

import requests as http_requests
from flask import redirect, request, session, url_for

from .extensions import db

# ── Constants ──────────────────────────────────────────────────────────────
FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY", "")

# Username rules: 3–20 chars, lowercase letters, digits, underscores only.
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")


# ── Auth decorator ─────────────────────────────────────────────────────────

def login_required(f):
    """Redirect unauthenticated users to the login page."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("uid"):
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


# ── CSRF helpers ───────────────────────────────────────────────────────────

def generate_csrf_token():
    """Generate (or reuse) a cryptographically secure per-session CSRF token."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


def validate_csrf():
    """Return True only when the submitted token matches the session token."""
    submitted = request.form.get("_csrf_token", "")
    expected  = session.get("_csrf_token", "")
    return bool(submitted and expected and secrets.compare_digest(submitted, expected))


# ── Rate limiter ────────────────────────────────────────────────────────────
# Simple in-memory sliding-window rate limiter.
# Cloud Run: each instance has its own counter — this is intentional and
# sufficient for brute-force protection on the free tier (1 instance).
# No extra packages required.

_rl_lock    = threading.Lock()
_rl_buckets: dict[str, list[float]] = defaultdict(list)

# Configuration: max attempts per window per IP
_RL_MAX_ATTEMPTS = 10       # allow 10 POST attempts …
_RL_WINDOW_SECS  = 60 * 5  # … per 5-minute window


def _get_client_ip() -> str:
    """Return the real client IP, honoring X-Forwarded-For (Cloud Run sets this)."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def is_rate_limited(key_prefix: str) -> bool:
    """
    Return True if the current IP has exceeded the allowed POST attempts
    for *key_prefix* (e.g. 'login' or 'register') within the time window.
    Automatically purges old entries to keep memory bounded.
    """
    ip  = _get_client_ip()
    key = f"{key_prefix}:{ip}"
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - _RL_WINDOW_SECS

    with _rl_lock:
        # Keep only timestamps within the current window
        _rl_buckets[key] = [t for t in _rl_buckets[key] if t > cutoff]
        if len(_rl_buckets[key]) >= _RL_MAX_ATTEMPTS:
            return True
        _rl_buckets[key].append(now)
        return False


# ── Firebase Auth REST wrappers ────────────────────────────────────────────

def firebase_sign_in(email, password):
    """Call Firebase signInWithPassword REST endpoint; return JSON response."""
    url = (
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
        f"?key={FIREBASE_API_KEY}"
    )
    try:
        res = http_requests.post(
            url,
            json={"email": email, "password": password, "returnSecureToken": True},
            timeout=10,
        )
        return res.json()
    except http_requests.RequestException:
        return {"error": {"message": "Network error. Please try again."}}


def firebase_sign_up(email, password):
    """Call Firebase signUp REST endpoint; return JSON response."""
    url = (
        "https://identitytoolkit.googleapis.com/v1/accounts:signUp"
        f"?key={FIREBASE_API_KEY}"
    )
    try:
        res = http_requests.post(
            url,
            json={"email": email, "password": password, "returnSecureToken": True},
            timeout=10,
        )
        return res.json()
    except http_requests.RequestException:
        return {"error": {"message": "Network error. Please try again."}}


def firebase_change_password(id_token, new_password):
    """
    Call Firebase REST update endpoint to change the authenticated user's password.
    Requires a fresh idToken obtained by re-authenticating the user first.
    Returns the JSON response dict — check for 'error' key on failure.
    """
    url = (
        "https://identitytoolkit.googleapis.com/v1/accounts:update"
        f"?key={FIREBASE_API_KEY}"
    )
    try:
        res = http_requests.post(
            url,
            json={"idToken": id_token, "password": new_password, "returnSecureToken": True},
            timeout=10,
        )
        return res.json()
    except http_requests.RequestException:
        return {"error": {"message": "Network error. Please try again."}}


# ── Firestore query helpers ────────────────────────────────────────────────

def get_approved_following_uids(uid):
    """Return list of UIDs that *uid* is currently approved to follow."""
    docs = db.collection("following").document(uid).collection("approved").stream()
    return [doc.id for doc in docs]


def get_pending_count(uid):
    """Return number of pending follow requests received by *uid*."""
    docs = (
        db.collection("follow_requests")
        .where("to_uid", "==", uid)
        .where("status", "==", "pending")
        .stream()
    )
    return sum(1 for _ in docs)


def get_user(uid):
    """Fetch a user document by UID; returns None if it does not exist."""
    doc = db.collection("users").document(uid).get()
    return doc.to_dict() if doc.exists else None


# ── Formatting ─────────────────────────────────────────────────────────────

def fmt_dt(dt):
    """Format a datetime (or Firestore Timestamp) for human-readable display."""
    if not dt:
        return ""
    if hasattr(dt, "strftime"):
        return dt.strftime("%d %b %Y, %I:%M %p")
    return str(dt)


def utcnow():
    """Return the current UTC time as a timezone-aware datetime object."""
    return datetime.now(timezone.utc)


# ── File upload validation ──────────────────────────────────────────────────

def allowed_file(filename, allowed_extensions):
    """Return True if *filename* has an extension in *allowed_extensions*."""
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in allowed_extensions
    )
