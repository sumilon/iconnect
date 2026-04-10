"""
Auth blueprint — /register, /login, /logout, /change-password routes.
"""

from flask import Blueprint, redirect, render_template, request, session, url_for

from .extensions import db
from .helpers import (
    USERNAME_RE,
    firebase_change_password,
    firebase_sign_in,
    firebase_sign_up,
    generate_csrf_token,
    is_rate_limited,
    utcnow,
    validate_csrf,
)

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Show registration form (GET) or process new account creation (POST)."""
    if session.get("uid"):
        return redirect(url_for("main.feed"))

    if request.method == "GET":
        return render_template("register.html", csrf_token=generate_csrf_token())

    # ── Rate limit: max 10 attempts per IP per 5 minutes ───────────────────
    if is_rate_limited("register"):
        return render_template("register.html",
                               error="Too many attempts. Please wait a few minutes and try again.",
                               csrf_token=generate_csrf_token()), 429

    # ── CSRF guard ─────────────────────────────────────────────────────────
    if not validate_csrf():
        return render_template("register.html", error="Invalid form submission.",
                               csrf_token=generate_csrf_token())

    username = request.form.get("username", "").strip().lower()
    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()

    # ── Field presence ──────────────────────────────────────────────────────
    if not username or not email or not password:
        return render_template("register.html", error="All fields are required.",
                               csrf_token=generate_csrf_token())

    # ── Username format: 3–20 chars, lowercase letters / digits / underscore ─
    if not USERNAME_RE.match(username):
        return render_template(
            "register.html",
            error="Username must be 3–20 characters: letters, numbers, underscores only.",
            csrf_token=generate_csrf_token(),
        )

    # ── Password minimum length ─────────────────────────────────────────────
    if len(password) < 6:
        return render_template("register.html",
                               error="Password must be at least 6 characters.",
                               csrf_token=generate_csrf_token())

    # ── Username uniqueness check in Firestore ──────────────────────────────
    if db.collection("users").where("username", "==", username).get():
        return render_template("register.html", error="Username already taken.",
                               csrf_token=generate_csrf_token())

    # ── Create Firebase Auth account ────────────────────────────────────────
    result = firebase_sign_up(email, password)
    if "error" in result:
        return render_template("register.html", error=result["error"]["message"],
                               csrf_token=generate_csrf_token())

    # ── Write public user profile to Firestore ─────────────────────────────
    uid = result["localId"]
    db.collection("users").document(uid).set({
        "uid":             uid,
        "username":        username,
        "email":           email,
        "bio":             "",
        "follower_count":  0,
        "following_count": 0,
        "post_count":      0,
        "created_at":      utcnow(),
    })

    session["uid"]      = uid
    session["username"] = username
    return redirect(url_for("main.feed"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Show login form (GET) or authenticate an existing user (POST)."""
    if session.get("uid"):
        return redirect(url_for("main.feed"))

    if request.method == "GET":
        msg = request.args.get("msg")
        success = "Password changed successfully. Please log in again." if msg == "password_changed" else None
        return render_template("login.html", success=success, csrf_token=generate_csrf_token())

    # ── Rate limit: max 10 attempts per IP per 5 minutes ───────────────────
    if is_rate_limited("login"):
        return render_template("login.html",
                               error="Too many attempts. Please wait a few minutes and try again.",
                               csrf_token=generate_csrf_token()), 429

    # ── CSRF guard ─────────────────────────────────────────────────────────
    if not validate_csrf():
        return render_template("login.html", error="Invalid form submission.",
                               csrf_token=generate_csrf_token())

    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()

    if not email or not password:
        return render_template("login.html", error="Email and password are required.",
                               csrf_token=generate_csrf_token())

    # ── Firebase Auth verification ──────────────────────────────────────────
    result = firebase_sign_in(email, password)
    if "error" in result:
        return render_template("login.html", error=result["error"]["message"],
                               csrf_token=generate_csrf_token())

    # ── Load user profile from Firestore ───────────────────────────────────
    uid      = result["localId"]
    user_doc = db.collection("users").document(uid).get()
    if not user_doc.exists:
        return render_template("login.html", error="User profile not found.",
                               csrf_token=generate_csrf_token())

    user = user_doc.to_dict()
    session["uid"]      = uid
    session["username"] = user["username"]
    return redirect(url_for("main.feed"))


@auth_bp.route("/change-password", methods=["GET", "POST"])
def change_password():
    """Allow a logged-in user to change their password."""
    if not session.get("uid"):
        return redirect(url_for("auth.login"))

    if request.method == "GET":
        return render_template("change_password.html",
                               csrf_token=generate_csrf_token())

    # ── CSRF guard ─────────────────────────────────────────────────────────
    if not validate_csrf():
        return render_template("change_password.html",
                               error="Invalid form submission.",
                               csrf_token=generate_csrf_token())

    current_password = request.form.get("current_password", "").strip()
    new_password     = request.form.get("new_password", "").strip()
    confirm_password = request.form.get("confirm_password", "").strip()

    # ── Field presence ──────────────────────────────────────────────────────
    if not current_password or not new_password or not confirm_password:
        return render_template("change_password.html",
                               error="All fields are required.",
                               csrf_token=generate_csrf_token())

    # ── New password length ─────────────────────────────────────────────────
    if len(new_password) < 6:
        return render_template("change_password.html",
                               error="New password must be at least 6 characters.",
                               csrf_token=generate_csrf_token())

    # ── Confirm match ───────────────────────────────────────────────────────
    if new_password != confirm_password:
        return render_template("change_password.html",
                               error="New passwords do not match.",
                               csrf_token=generate_csrf_token())

    # ── Same password check ─────────────────────────────────────────────────
    if current_password == new_password:
        return render_template("change_password.html",
                               error="New password must be different from your current password.",
                               csrf_token=generate_csrf_token())

    # ── Re-authenticate with current password to get a fresh idToken ────────
    # Firebase requires a recent idToken to authorise a password change.
    user_doc = db.collection("users").document(session["uid"]).get()
    if not user_doc.exists:
        return render_template("change_password.html",
                               error="User not found.",
                               csrf_token=generate_csrf_token())

    email = user_doc.to_dict().get("email", "")
    auth_result = firebase_sign_in(email, current_password)
    if "error" in auth_result:
        return render_template("change_password.html",
                               error="Current password is incorrect.",
                               csrf_token=generate_csrf_token())

    # ── Change password via Firebase REST API ───────────────────────────────
    id_token      = auth_result["idToken"]
    change_result = firebase_change_password(id_token, new_password)
    if "error" in change_result:
        return render_template("change_password.html",
                               error=change_result["error"]["message"],
                               csrf_token=generate_csrf_token())

    # ── Success: clear session and force re-login ───────────────────────────
    session.clear()
    return redirect(url_for("auth.login") + "?msg=password_changed")


@auth_bp.route("/logout")
def logout():
    """Invalidate the session and redirect to the landing page."""
    session.clear()
    return redirect(url_for("main.index"))
