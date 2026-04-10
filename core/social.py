"""
Social blueprint — follow, approve, decline, unfollow routes.
"""

from firebase_admin import firestore as fs
from flask import Blueprint, redirect, request, session, url_for

from .extensions import db
from .helpers import (
    login_required,
    utcnow,
    validate_csrf,
)

social_bp = Blueprint("social", __name__)


@social_bp.route("/follow/<target_uid>", methods=["POST"])
@login_required
def send_follow_request(target_uid):
    uid = session["uid"]
    if uid == target_uid:
        return redirect(url_for("main.my_profile"))

    # ── CSRF guard ─────────────────────────────────────────────────────────
    if not validate_csrf():
        return redirect(url_for("main.view_profile", target_uid=target_uid))

    existing = (
        db.collection("follow_requests")
        .where("from_uid", "==", uid)
        .where("to_uid", "==", target_uid)
        .limit(1)
        .get()
    )
    if existing:
        doc    = existing[0]
        status = doc.to_dict().get("status")
        if status in ("pending", "approved"):
            return redirect(url_for("main.view_profile", target_uid=target_uid))
        if status == "declined":
            doc.reference.update({"status": "pending", "created_at": utcnow()})
    else:
        target_doc  = db.collection("users").document(target_uid).get()
        target_user = target_doc.to_dict() if target_doc.exists else {}
        db.collection("follow_requests").add({
            "from_uid":      uid,
            "from_username": session["username"],
            "to_uid":        target_uid,
            "to_username":   target_user.get("username", ""),
            "status":        "pending",
            "created_at":    utcnow(),
        })

    return redirect(url_for("main.view_profile", target_uid=target_uid))


@social_bp.route("/follow/approve/<request_id>", methods=["POST"])
@login_required
def approve_follow(request_id):
    uid = session["uid"]

    # ── CSRF guard ─────────────────────────────────────────────────────────
    if not validate_csrf():
        return redirect(url_for("main.my_profile"))

    req_doc = db.collection("follow_requests").document(request_id).get()
    if not req_doc.exists:
        return redirect(url_for("main.my_profile"))

    req = req_doc.to_dict()
    if req["to_uid"] != uid:
        return redirect(url_for("main.my_profile"))

    from_uid      = req["from_uid"]
    from_username = req["from_username"]
    my_username   = session.get("username", "")

    db.collection("follow_requests").document(request_id).update({"status": "approved"})
    db.collection("followers").document(uid).collection("approved").document(from_uid).set(
        {"uid": from_uid, "username": from_username, "created_at": utcnow()}
    )
    db.collection("following").document(from_uid).collection("approved").document(uid).set(
        {"uid": uid, "username": my_username, "created_at": utcnow()}
    )
    db.collection("users").document(uid).update({"follower_count": fs.Increment(1)})
    db.collection("users").document(from_uid).update({"following_count": fs.Increment(1)})
    return redirect(url_for("main.my_profile"))


@social_bp.route("/follow/decline/<request_id>", methods=["POST"])
@login_required
def decline_follow(request_id):
    uid = session["uid"]

    # ── CSRF guard ─────────────────────────────────────────────────────────
    if not validate_csrf():
        return redirect(url_for("main.my_profile"))

    req_doc = db.collection("follow_requests").document(request_id).get()
    if req_doc.exists and req_doc.to_dict().get("to_uid") == uid:
        db.collection("follow_requests").document(request_id).update({"status": "declined"})

    return redirect(url_for("main.my_profile"))


@social_bp.route("/unfollow/<target_uid>", methods=["POST"])
@login_required
def unfollow(target_uid):
    uid = session["uid"]

    # ── CSRF guard ─────────────────────────────────────────────────────────
    if not validate_csrf():
        return redirect(url_for("main.view_profile", target_uid=target_uid))

    db.collection("followers").document(target_uid).collection("approved").document(uid).delete()
    db.collection("following").document(uid).collection("approved").document(target_uid).delete()

    existing = (
        db.collection("follow_requests")
        .where("from_uid", "==", uid)
        .where("to_uid", "==", target_uid)
        .limit(1)
        .get()
    )
    for doc in existing:
        doc.reference.delete()

    db.collection("users").document(target_uid).update({"follower_count": fs.Increment(-1)})
    db.collection("users").document(uid).update({"following_count": fs.Increment(-1)})
    return redirect(url_for("main.view_profile", target_uid=target_uid))
