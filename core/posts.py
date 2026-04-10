"""
Posts blueprint — /upload and /post/delete/<post_id> routes.
"""

import uuid

from firebase_admin import firestore as fs
from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from .extensions import db, storage_client
from .helpers import (
    allowed_file,
    get_pending_count,
    login_required,
    utcnow,
    validate_csrf,
)

posts_bp = Blueprint("posts", __name__)


@posts_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    """Show the upload form (GET) or handle image + caption submission (POST)."""
    uid           = session["uid"]
    pending_count = get_pending_count(uid)

    if request.method == "GET":
        return render_template("upload.html", pending_count=pending_count)

    # ── CSRF guard ─────────────────────────────────────────────────────────
    if not validate_csrf():
        return render_template("upload.html", error="Invalid form submission.",
                               pending_count=pending_count)

    image_file = request.files.get("image")
    caption    = request.form.get("caption", "").strip()

    # ── Validate file presence ──────────────────────────────────────────────
    if not image_file or not image_file.filename:
        return render_template("upload.html", error="Please select an image.",
                               pending_count=pending_count)

    # ── Validate file type ──────────────────────────────────────────────────
    allowed = current_app.config["ALLOWED_EXTENSIONS"]
    if not allowed_file(image_file.filename, allowed):
        return render_template(
            "upload.html",
            error=f"File type not supported. Allowed: {', '.join(sorted(allowed))}.",
            pending_count=pending_count,
        )

    # ── Sanitise filename and upload to GCS ────────────────────────────────
    safe_name   = secure_filename(image_file.filename)
    filename    = f"{uuid.uuid4().hex}_{safe_name}"
    gcs_path    = f"posts/{filename}"
    bucket_name = current_app.config["BUCKET_NAME"]
    bucket      = storage_client.bucket(bucket_name)
    blob        = bucket.blob(gcs_path)
    blob.upload_from_file(image_file, content_type=image_file.content_type)

    image_url = f"https://storage.googleapis.com/{bucket_name}/{gcs_path}"

    # ── Persist post to Firestore ───────────────────────────────────────────
    db.collection("posts").add({
        "uid":        uid,
        "username":   session["username"],
        "image_url":  image_url,
        "caption":    caption,
        "gcs_path":   gcs_path,
        "created_at": utcnow(),
    })
    db.collection("users").document(uid).update({"post_count": fs.Increment(1)})
    return redirect(url_for("main.my_profile"))


@posts_bp.route("/post/delete/<post_id>", methods=["POST"])
@login_required
def delete_post(post_id):
    """Delete a post — removes both the Firestore document and the GCS blob."""
    uid = session["uid"]

    # ── CSRF guard ─────────────────────────────────────────────────────────
    if not validate_csrf():
        return redirect(url_for("main.my_profile"))

    post_doc = db.collection("posts").document(post_id).get()
    if not post_doc.exists:
        return redirect(url_for("main.my_profile"))

    post = post_doc.to_dict()

    # ── Ownership check ─────────────────────────────────────────────────────
    if post["uid"] != uid:
        return redirect(url_for("main.my_profile"))

    # ── Delete GCS blob to avoid orphaned storage costs ────────────────────
    gcs_path = post.get("gcs_path")
    if gcs_path:
        try:
            storage_client.bucket(current_app.config["BUCKET_NAME"]).blob(gcs_path).delete()
        except Exception:
            pass   # blob may already be gone; proceed with Firestore delete

    # ── Delete Firestore document and decrement counter ─────────────────────
    db.collection("posts").document(post_id).delete()
    db.collection("users").document(uid).update({"post_count": fs.Increment(-1)})
    return redirect(url_for("main.my_profile"))
