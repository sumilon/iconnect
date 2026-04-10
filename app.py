from flask import Flask, request, render_template, redirect, url_for, session
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud import storage
import uuid
from datetime import datetime
import requests as http_requests
import os
import json

app = Flask(__name__)

# ══════════════════════════════════════════════════════════════════════════
#  CONFIG — reads from Secret Manager env vars on Cloud Run,
#           falls back to local values for local development
# ══════════════════════════════════════════════════════════════════════════

app.secret_key   = os.environ.get("FLASK_SECRET_KEY", "local-dev-secret-change-this")
BUCKET_NAME      = os.environ.get("BUCKET_NAME", "your-bucket-name")
FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY", "your-firebase-api-key")

# ── Firebase + GCS Init ────────────────────────────────────────────────────
if os.environ.get("GOOGLE_CREDENTIALS"):
    cred_dict      = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    cred           = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    db             = firestore.client()
    storage_client = storage.Client.from_service_account_info(cred_dict)
else:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
    db             = firestore.client()
    storage_client = storage.Client.from_service_account_json("serviceAccountKey.json")


# ══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("uid"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def firebase_sign_in(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
    res = http_requests.post(url, json={"email": email, "password": password, "returnSecureToken": True})
    return res.json()

def firebase_sign_up(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_API_KEY}"
    res = http_requests.post(url, json={"email": email, "password": password, "returnSecureToken": True})
    return res.json()

def get_approved_following_uids(uid):
    docs = db.collection("following").document(uid).collection("approved").stream()
    return [doc.id for doc in docs]

def get_pending_count(uid):
    docs = db.collection("follow_requests").where("to_uid", "==", uid).where("status", "==", "pending").stream()
    return sum(1 for _ in docs)

def fmt(dt):
    return dt.strftime("%d %b %Y, %I:%M %p") if dt else ""


# ══════════════════════════════════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    if session.get("uid"):
        return redirect(url_for("feed"))
    return render_template("landing.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")
    username = request.form.get("username", "").strip().lower()
    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    if not username or not email or not password:
        return render_template("register.html", error="All fields are required.")
    if len(password) < 6:
        return render_template("register.html", error="Password must be at least 6 characters.")
    existing = db.collection("users").where("username", "==", username).get()
    if existing:
        return render_template("register.html", error="Username already taken.")
    result = firebase_sign_up(email, password)
    if "error" in result:
        return render_template("register.html", error=result["error"]["message"])
    uid = result["localId"]
    db.collection("users").document(uid).set({
        "uid": uid, "username": username, "email": email, "bio": "",
        "follower_count": 0, "following_count": 0, "post_count": 0,
        "created_at": datetime.utcnow()
    })
    session["uid"]      = uid
    session["username"] = username
    return redirect(url_for("feed"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    result   = firebase_sign_in(email, password)
    if "error" in result:
        return render_template("login.html", error=result["error"]["message"])
    uid      = result["localId"]
    user_doc = db.collection("users").document(uid).get()
    if not user_doc.exists:
        return render_template("login.html", error="User profile not found.")
    user = user_doc.to_dict()
    session["uid"]      = uid
    session["username"] = user["username"]
    return redirect(url_for("feed"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ══════════════════════════════════════════════════════════════════════════
#  FEED
# ══════════════════════════════════════════════════════════════════════════

@app.route("/feed")
@login_required
def feed():
    uid            = session["uid"]
    following_uids = get_approved_following_uids(uid)
    pending_count  = get_pending_count(uid)
    posts          = []
    if following_uids:
        for i in range(0, len(following_uids), 30):
            batch = following_uids[i:i+30]
            for doc in db.collection("posts").where("uid", "in", batch).stream():
                d = doc.to_dict()
                d["id"]            = doc.id
                d["created_at_dt"] = d["created_at"]
                d["created_at"]    = fmt(d["created_at"])
                posts.append(d)
        posts.sort(key=lambda x: x["created_at_dt"], reverse=True)
    return render_template("feed.html", posts=posts,
                           following_count=len(following_uids),
                           pending_count=pending_count)


# ══════════════════════════════════════════════════════════════════════════
#  UPLOAD
# ══════════════════════════════════════════════════════════════════════════

@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    uid           = session["uid"]
    pending_count = get_pending_count(uid)
    if request.method == "GET":
        return render_template("upload.html", pending_count=pending_count)
    image_file = request.files.get("image")
    caption    = request.form.get("caption", "").strip()
    if not image_file:
        return render_template("upload.html", error="Please select an image.", pending_count=pending_count)
    filename  = f"{uuid.uuid4()}_{image_file.filename}"
    bucket    = storage_client.bucket(BUCKET_NAME)
    blob      = bucket.blob(f"posts/{filename}")
    blob.upload_from_file(image_file, content_type=image_file.content_type)
    image_url = f"https://storage.googleapis.com/{BUCKET_NAME}/posts/{filename}"
    db.collection("posts").add({
        "uid": uid, "username": session["username"],
        "image_url": image_url, "caption": caption,
        "created_at": datetime.utcnow()
    })
    db.collection("users").document(uid).update({"post_count": firestore.Increment(1)})
    return redirect(url_for("my_profile"))


# ══════════════════════════════════════════════════════════════════════════
#  SEARCH
# ══════════════════════════════════════════════════════════════════════════

@app.route("/search")
@login_required
def search():
    uid           = session["uid"]
    pending_count = get_pending_count(uid)
    query         = request.args.get("q", "").strip().lower()
    results       = []
    if query:
        docs = db.collection("users") \
            .where("username", ">=", query) \
            .where("username", "<=", query + "\uf8ff") \
            .limit(20).stream()
        for doc in docs:
            d = doc.to_dict()
            if d["uid"] != uid:
                results.append(d)
    return render_template("search.html", results=results, query=query, pending_count=pending_count)


# ══════════════════════════════════════════════════════════════════════════
#  PROFILE — own
# ══════════════════════════════════════════════════════════════════════════

@app.route("/profile")
@login_required
def my_profile():
    uid           = session["uid"]
    pending_count = get_pending_count(uid)
    user          = db.collection("users").document(uid).get().to_dict()
    posts = []
    for doc in db.collection("posts").where("uid", "==", uid) \
            .order_by("created_at", direction=firestore.Query.DESCENDING).stream():
        d = doc.to_dict()
        d["id"]         = doc.id
        d["created_at"] = fmt(d["created_at"])
        posts.append(d)
    pending_requests = []
    for doc in db.collection("follow_requests") \
            .where("to_uid", "==", uid).where("status", "==", "pending").stream():
        d = doc.to_dict()
        d["request_id"] = doc.id
        pending_requests.append(d)
    return render_template("profile.html", user=user, posts=posts, is_own=True,
                           pending_requests=pending_requests, pending_count=pending_count)


# ══════════════════════════════════════════════════════════════════════════
#  PROFILE — other user
# ══════════════════════════════════════════════════════════════════════════

@app.route("/profile/<target_uid>")
@login_required
def view_profile(target_uid):
    uid = session["uid"]
    if target_uid == uid:
        return redirect(url_for("my_profile"))
    pending_count = get_pending_count(uid)
    user_doc      = db.collection("users").document(target_uid).get()
    if not user_doc.exists:
        return redirect(url_for("search"))
    user          = user_doc.to_dict()
    follow_status = None
    existing = db.collection("follow_requests") \
        .where("from_uid", "==", uid).where("to_uid", "==", target_uid).limit(1).get()
    if existing:
        follow_status = existing[0].to_dict().get("status")
    posts = []
    if follow_status == "approved":
        for doc in db.collection("posts").where("uid", "==", target_uid) \
                .order_by("created_at", direction=firestore.Query.DESCENDING).stream():
            d = doc.to_dict()
            d["id"]         = doc.id
            d["created_at"] = fmt(d["created_at"])
            posts.append(d)
    return render_template("profile.html", user=user, posts=posts, is_own=False,
                           follow_status=follow_status, target_uid=target_uid,
                           pending_count=pending_count)


# ══════════════════════════════════════════════════════════════════════════
#  FOLLOW SYSTEM
# ══════════════════════════════════════════════════════════════════════════

@app.route("/follow/<target_uid>", methods=["POST"])
@login_required
def send_follow_request(target_uid):
    uid = session["uid"]
    if uid == target_uid:
        return redirect(url_for("my_profile"))
    existing = db.collection("follow_requests") \
        .where("from_uid", "==", uid).where("to_uid", "==", target_uid).limit(1).get()
    if existing:
        doc    = existing[0]
        status = doc.to_dict().get("status")
        if status in ("pending", "approved"):
            return redirect(url_for("view_profile", target_uid=target_uid))
        if status == "declined":
            doc.reference.update({"status": "pending", "created_at": datetime.utcnow()})
    else:
        target_user = db.collection("users").document(target_uid).get().to_dict()
        db.collection("follow_requests").add({
            "from_uid": uid, "from_username": session["username"],
            "to_uid": target_uid, "to_username": target_user.get("username", ""),
            "status": "pending", "created_at": datetime.utcnow()
        })
    return redirect(url_for("view_profile", target_uid=target_uid))

@app.route("/follow/approve/<request_id>", methods=["POST"])
@login_required
def approve_follow(request_id):
    uid     = session["uid"]
    req_doc = db.collection("follow_requests").document(request_id).get()
    if not req_doc.exists:
        return redirect(url_for("my_profile"))
    req = req_doc.to_dict()
    if req["to_uid"] != uid:
        return redirect(url_for("my_profile"))
    from_uid      = req["from_uid"]
    from_username = req["from_username"]
    my_user       = db.collection("users").document(uid).get().to_dict()
    db.collection("follow_requests").document(request_id).update({"status": "approved"})
    db.collection("followers").document(uid).collection("approved").document(from_uid).set(
        {"uid": from_uid, "username": from_username, "created_at": datetime.utcnow()})
    db.collection("following").document(from_uid).collection("approved").document(uid).set(
        {"uid": uid, "username": my_user.get("username", ""), "created_at": datetime.utcnow()})
    db.collection("users").document(uid).update({"follower_count": firestore.Increment(1)})
    db.collection("users").document(from_uid).update({"following_count": firestore.Increment(1)})
    return redirect(url_for("my_profile"))

@app.route("/follow/decline/<request_id>", methods=["POST"])
@login_required
def decline_follow(request_id):
    uid     = session["uid"]
    req_doc = db.collection("follow_requests").document(request_id).get()
    if req_doc.exists and req_doc.to_dict().get("to_uid") == uid:
        db.collection("follow_requests").document(request_id).update({"status": "declined"})
    return redirect(url_for("my_profile"))

@app.route("/unfollow/<target_uid>", methods=["POST"])
@login_required
def unfollow(target_uid):
    uid = session["uid"]
    db.collection("followers").document(target_uid).collection("approved").document(uid).delete()
    db.collection("following").document(uid).collection("approved").document(target_uid).delete()
    existing = db.collection("follow_requests") \
        .where("from_uid", "==", uid).where("to_uid", "==", target_uid).limit(1).get()
    for doc in existing:
        doc.reference.delete()
    db.collection("users").document(target_uid).update({"follower_count": firestore.Increment(-1)})
    db.collection("users").document(uid).update({"following_count": firestore.Increment(-1)})
    return redirect(url_for("view_profile", target_uid=target_uid))


if __name__ == "__main__":
    app.run(debug=True)