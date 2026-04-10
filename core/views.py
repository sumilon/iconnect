"""
Main views blueprint — index, feed, search, profile pages.
"""

from firebase_admin import firestore as fs
from flask import Blueprint, Response, redirect, render_template, request, session, url_for

from .extensions import db
from .helpers import (
    fmt_dt,
    generate_csrf_token,
    get_approved_following_uids,
    get_pending_count,
    login_required,
)

main_bp = Blueprint("main", __name__)

# Posts shown per feed page
_PAGE_SIZE = 10

# ── Favicon ────────────────────────────────────────────────────────────────

_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<rect width="100" height="100" rx="22" fill="#1877f2"/>'
    '<text y="75" x="50" text-anchor="middle" font-size="62" '
    'font-family="Segoe UI Emoji,Apple Color Emoji,sans-serif">&#128279;</text>'
    '</svg>'
)

@main_bp.route("/favicon.svg")
def favicon():
    """Serve the app favicon as a plain SVG — no Jinja2 rendering involved."""
    return Response(_FAVICON_SVG, mimetype="image/svg+xml")


# ── Landing ────────────────────────────────────────────────────────────────

@main_bp.route("/")
def index():
    if session.get("uid"):
        return redirect(url_for("main.feed"))
    return render_template("landing.html")


# ── Feed (paginated) ────────────────────────────────────────────────────────

@main_bp.route("/feed")
@login_required
def feed():
    uid            = session["uid"]
    following_uids = get_approved_following_uids(uid)
    pending_count  = get_pending_count(uid)
    posts          = []

    # "after" query param holds the Firestore document ID of the last post
    # on the previous page, used as a cursor.
    after_doc_id = request.args.get("after", None)

    if following_uids:
        # Collect all matching posts across 30-item batches (Firestore "in" limit)
        candidate_docs = []
        for i in range(0, len(following_uids), 30):
            batch = following_uids[i : i + 30]
            for doc in (
                db.collection("posts")
                .where("uid", "in", batch)
                .order_by("created_at", direction=fs.Query.DESCENDING)
                .limit(_PAGE_SIZE * 3)        # over-fetch to allow cross-batch sort
                .stream()
            ):
                candidate_docs.append(doc)

        # Sort all candidates newest-first, then apply cursor + page window
        candidate_docs.sort(
            key=lambda d: d.to_dict().get("created_at") or "",
            reverse=True,
        )

        # Find cursor position
        start_idx = 0
        if after_doc_id:
            for idx, doc in enumerate(candidate_docs):
                if doc.id == after_doc_id:
                    start_idx = idx + 1
                    break

        page_docs = candidate_docs[start_idx : start_idx + _PAGE_SIZE]
        has_next  = len(candidate_docs) > start_idx + _PAGE_SIZE
        last_id   = page_docs[-1].id if page_docs else None

        for doc in page_docs:
            d               = doc.to_dict()
            d["id"]         = doc.id
            d["created_at"] = fmt_dt(d.get("created_at"))
            posts.append(d)
    else:
        has_next = False
        last_id  = None

    return render_template(
        "feed.html",
        posts=posts,
        following_count=len(following_uids),
        pending_count=pending_count,
        has_next=has_next,
        last_id=last_id,
        after_doc_id=after_doc_id,   # so template knows if we're past page 1
    )


# ── Search ─────────────────────────────────────────────────────────────────

@main_bp.route("/search")
@login_required
def search():
    uid           = session["uid"]
    pending_count = get_pending_count(uid)
    query         = request.args.get("q", "").strip().lower()
    results       = []

    if query:
        docs = (
            db.collection("users")
            .where("username", ">=", query)
            .where("username", "<=", query + "\uf8ff")
            .limit(20)
            .stream()
        )
        for doc in docs:
            d = doc.to_dict()
            if d.get("uid") != uid:
                results.append(d)

    return render_template(
        "search.html",
        results=results,
        query=query,
        pending_count=pending_count,
    )


# ── Own Profile ────────────────────────────────────────────────────────────

@main_bp.route("/profile")
@login_required
def my_profile():
    uid           = session["uid"]
    pending_count = get_pending_count(uid)
    user_doc      = db.collection("users").document(uid).get()
    user          = user_doc.to_dict() if user_doc.exists else {}

    posts = []
    for doc in (
        db.collection("posts")
        .where("uid", "==", uid)
        .order_by("created_at", direction=fs.Query.DESCENDING)
        .limit(50)
        .stream()
    ):
        d               = doc.to_dict()
        d["id"]         = doc.id
        d["created_at"] = fmt_dt(d.get("created_at"))
        posts.append(d)

    pending_requests = []
    for doc in (
        db.collection("follow_requests")
        .where("to_uid", "==", uid)
        .where("status", "==", "pending")
        .stream()
    ):
        d               = doc.to_dict()
        d["request_id"] = doc.id
        pending_requests.append(d)

    return render_template(
        "profile.html",
        user=user,
        posts=posts,
        is_own=True,
        pending_requests=pending_requests,
        pending_count=pending_count,
        csrf_token=generate_csrf_token(),
    )


# ── Other User's Profile ───────────────────────────────────────────────────

@main_bp.route("/profile/<target_uid>")
@login_required
def view_profile(target_uid):
    uid = session["uid"]
    if target_uid == uid:
        return redirect(url_for("main.my_profile"))

    pending_count = get_pending_count(uid)
    user_doc      = db.collection("users").document(target_uid).get()
    if not user_doc.exists:
        return redirect(url_for("main.search"))

    user          = user_doc.to_dict()
    follow_status = None
    existing = (
        db.collection("follow_requests")
        .where("from_uid", "==", uid)
        .where("to_uid", "==", target_uid)
        .limit(1)
        .get()
    )
    if existing:
        follow_status = existing[0].to_dict().get("status")

    posts = []
    if follow_status == "approved":
        for doc in (
            db.collection("posts")
            .where("uid", "==", target_uid)
            .order_by("created_at", direction=fs.Query.DESCENDING)
            .limit(50)
            .stream()
        ):
            d               = doc.to_dict()
            d["id"]         = doc.id
            d["created_at"] = fmt_dt(d.get("created_at"))
            posts.append(d)

    return render_template(
        "profile.html",
        user=user,
        posts=posts,
        is_own=False,
        follow_status=follow_status,
        target_uid=target_uid,
        pending_count=pending_count,
        csrf_token=generate_csrf_token(),
    )
