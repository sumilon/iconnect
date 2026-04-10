# PixelComm — Complete Deployment Guide
# Local Development + GCP Cloud Run Deployment

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Local Development Setup](#2-local-development-setup)
3. [Prepare Code for Cloud Run](#3-prepare-code-for-cloud-run)
4. [Push Code to GitHub](#4-push-code-to-github)
5. [Setup Secret Manager in GCP](#5-setup-secret-manager-in-gcp)
6. [Deploy to Cloud Run from GitHub](#6-deploy-to-cloud-run-from-github)
7. [Verify Deployment](#7-verify-deployment)
8. [Common Errors and Fixes](#8-common-errors-and-fixes)
9. [Firestore Indexes Required](#9-firestore-indexes-required)

---

## 1. Project Structure

```
pixelcomm/
├── app.py                    ← Flask backend
├── requirements.txt          ← Python dependencies
├── Procfile                  ← Tells Cloud Run how to start app
├── .gcloudignore             ← Files to exclude from deployment
├── .gitignore                ← Files to exclude from Git
└── templates/
    ├── base.html
    ├── landing.html
    ├── register.html
    ├── login.html
    ├── feed.html
    ├── search.html
    ├── profile.html
    └── upload.html
```

---

## 2. Local Development Setup

### Step 1 — Clone or create your project folder

```bash
mkdir pixelcomm
cd pixelcomm
```

### Step 2 — Create virtual environment

```bash
python -m venv .venv

# Activate on Windows:
.venv\Scripts\activate

# Activate on Mac/Linux:
source .venv/bin/activate
```

### Step 3 — Install dependencies

```bash
pip install flask firebase-admin google-cloud-storage requests gunicorn
pip freeze > requirements.txt
```

### Step 4 — Place your service account key

- Download `serviceAccountKey.json` from GCP Console
- Place it in the project root folder
- This is for local development only — never commit this file

### Step 5 — Update app.py with your values

Open `app.py` and update these 3 lines:

```python
FLASK_SECRET_KEY   = "any-random-string-you-choose"
BUCKET_NAME      = "your-gcs-bucket-name"
FIREBASE_API_KEY = "your-firebase-web-api-key"
```


### Step 6 — Run locally

```bash
python app.py
```

Open browser at: **http://localhost:5000**

---

## 3. Prepare Code for Cloud Run

Cloud Run needs a few extra files. Create all of these in your project root.

### File 1 — Procfile

This tells Cloud Run how to start your Flask app using gunicorn
(gunicorn is a production-grade server, better than Flask's built-in server).

Create a file named exactly `Procfile` (no extension) with this content:

```
web: gunicorn --bind 0.0.0.0:$PORT app:app
```

### File 2 — .gitignore

Create `.gitignore` to prevent secrets from being pushed to GitHub:

```
# Secret files — never commit these
serviceAccountKey.json
*.json

# Python
.venv/
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
*.egg-info/

# Environment
.env
.env.local

# IDE
.idea/
.vscode/
*.iml
```

### File 3 — .gcloudignore

Create `.gcloudignore` to exclude files from Cloud Run deployment:

```
.git/
.venv/
__pycache__/
*.pyc
serviceAccountKey.json
.env
README.md
```

## 4. Push Code to GitHub

### Step 1 — Create a GitHub repository

1. Go to [github.com](https://github.com) and sign in
2. Click **"New repository"** (+ icon top right)
3. Name it `pixelcomm`
4. Set to **Private** (recommended — your code is private)
5. Click **"Create repository"**

### Step 2 — Initialize Git and push

Run these commands in your project folder:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/pixelcomm.git
git push -u origin main
```

> Replace `YOUR_USERNAME` with your actual GitHub username.

### Step 3 — Verify .gitignore worked

Go to your GitHub repo in browser and confirm:
- `serviceAccountKey.json` is NOT listed ✅
- `*.json` files are NOT listed ✅
- Only code files are visible ✅

---

## 5. Setup Secret Manager in GCP

Secret Manager is GCP's secure vault for storing API keys, passwords,
and credentials. Cloud Run reads from it automatically.

### Step 1 — Enable Secret Manager API

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Select your project
3. Search **"Secret Manager"** in the top search bar → click it
4. Click **"Enable API"** if prompted
5. Wait for it to enable (~30 seconds)

### Step 2 — Create Secret 1: GOOGLE_CREDENTIALS

This stores your entire serviceAccountKey.json content as a secret.

1. In Secret Manager, click **"+ Create Secret"**
2. Fill in:
    - **Name**: `GOOGLE_CREDENTIALS`
    - **Secret value**: Open your `serviceAccountKey.json` file,
      select ALL the content and paste it here
3. Leave all other settings as default
4. Click **"Create Secret"**

### Step 3 — Create Secret 2: FIREBASE_API_KEY

1. Click **"+ Create Secret"**
2. Fill in:
    - **Name**: `FIREBASE_API_KEY`
    - **Secret value**: paste your Firebase Web API key
      (from Firebase Console → Project Settings → Your apps → apiKey)
3. Click **"Create Secret"**

### Step 4 — Create Secret 3: FLASK_SECRET_KEY

1. Click **"+ Create Secret"**
2. Fill in:
    - **Name**: `FLASK_SECRET_KEY`
    - **Secret value**: type any long random string
      e.g. `x7k2mP9qL4nR8vT3wY6jA1sD5hF0eU`
3. Click **"Create Secret"**

### Step 5 — Create Secret 4: BUCKET_NAME

1. Click **"+ Create Secret"**
2. Fill in:
    - **Name**: `BUCKET_NAME`
    - **Secret value**: your GCS bucket name
      e.g. `image-feed-poc-yourname`
3. Click **"Create Secret"**

You should now have 4 secrets listed:

```
GOOGLE_CREDENTIALS
FIREBASE_API_KEY
FLASK_SECRET_KEY
BUCKET_NAME
```

### Step 6 — Grant Cloud Run access to Secret Manager

Cloud Run runs as a service account. It needs permission to read secrets.

1. In GCP Console, search **"IAM & Admin"** → click **IAM**
2. Find the service account that looks like:
   ```
   PROJECT_NUMBER-compute@developer.gserviceaccount.com
   ```
   (This is the default Compute Engine service account)
3. Click the **edit pencil** ✏️ next to it
4. Click **"+ Add another role"**
5. Search and select: **"Secret Manager Secret Accessor"**
6. Click **"Save"**

---

## 6. Deploy to Cloud Run from GitHub

### Step 1 — Open Cloud Run

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Search **"Cloud Run"** → click it
3. Click **"+ Create Service"**

### Step 2 — Connect to GitHub repository

1. Under **"Deploy from"**, select **"Continuously deploy from a repository"**
2. Click **"Set up with Cloud Build"**
3. Click **"Authenticate"** → sign in with your GitHub account
4. Under **Repository**, click **"Select repository"**
5. Find and select your `pixelcomm` repo
6. Click **"Next"**

### Step 3 — Configure Build

1. **Branch**: `^main$`
2. **Build type**: select **"Go, Node.js, Python, Java..."**
   (This uses Buildpacks — no Dockerfile needed)
3. Click **"Save"**

### Step 4 — Configure Service Settings

Fill in these fields:

```
Service name    : pixelcomm
Region          : asia-south1   (same as your Firestore region)
CPU allocation  : CPU is only allocated during request processing
Minimum instances: 0            (scales to zero when not used — saves cost)
Maximum instances: 2            (enough for POC)
```

### Step 5 — Set Authentication

Under **"Authentication"**:
- Select **"Allow unauthenticated invocations"**
  (This makes your app publicly accessible on the internet)

### Step 6 — Add Environment Variables from Secret Manager

1. Scroll down to **"Container, Networking, Security"** → click to expand
2. Click the **"Variables & Secrets"** tab
3. Click **"+ Reference a Secret"** and add all 4 secrets:

| Environment Variable Name | Secret | Version |
|---|---|---|
| `GOOGLE_CREDENTIALS` | `GOOGLE_CREDENTIALS` | `latest` |
| `FIREBASE_API_KEY` | `FIREBASE_API_KEY` | `latest` |
| `FLASK_SECRET_KEY` | `FLASK_SECRET_KEY` | `latest` |
| `BUCKET_NAME` | `BUCKET_NAME` | `latest` |

For each one:
- Click **"+ Reference a Secret"**
- **Name**: type the environment variable name (left column)
- **Secret**: select from dropdown (right column)
- **Version**: select `latest`
- Click **"Done"**

### Step 7 — Set Container Port

1. Click the **"Container"** tab
2. Set **Container port** to `8080`

### Step 8 — Deploy

1. Click **"Create"** at the bottom
2. Cloud Run will:
    - Pull your code from GitHub
    - Build it automatically using Buildpacks
    - Deploy it as a live service
3. Wait **3-5 minutes** for the first deployment

### Step 9 — Get Your Live URL

Once deployed, you will see a green checkmark ✅ and a URL like:

```
https://pixelcomm-xxxxxxxxxx-uc.a.run.app
```

Click it — your app is live on the internet! 🎉

---

## 7. Verify Deployment

After deployment, test these things in order:

```
✅ Open the URL — landing page loads
✅ Register a new account
✅ Log in with that account
✅ Upload an image
✅ Log out and log back in — image still shows
✅ Register a second account
✅ Search for first account by username
✅ Send follow request
✅ Log in as first account — approve the request
✅ Log in as second account — see first user's posts in feed
```

---

## 8. Common Errors and Fixes

### Error: Module not found / Build failed

**Cause**: `requirements.txt` is missing a package.

**Fix**: Run locally and make sure all packages are listed:
```bash
pip freeze > requirements.txt
git add requirements.txt
git commit -m "Update requirements"
git push
```
Cloud Run will automatically redeploy when you push.

---

### Error: Permission denied on Secret Manager

**Cause**: Cloud Run service account doesn't have access to secrets.

**Fix**: Go to IAM → find `PROJECT_NUMBER-compute@developer.gserviceaccount.com`
→ add role **Secret Manager Secret Accessor**

---

### Error: Firestore index required

**Cause**: Query uses multiple fields without a composite index.

**Fix**: Copy the URL from the error message → open in browser → click Create Index → wait 2-3 minutes.

---

### Error: Port already in use (local)

**Fix**:
```bash
# Windows
netstat -ano | findstr :5000
taskkill /PID <PID> /F

# Mac/Linux
lsof -ti:5000 | xargs kill
```

---

### Error: 403 Forbidden on Cloud Storage upload

**Cause**: Billing not enabled or bucket permissions missing.

**Fix**:
- Make sure Firebase is on Blaze plan
- Make sure bucket has `allUsers` → `Storage Object Viewer` role

---

### App works locally but not on Cloud Run

**Cause**: Usually a missing environment variable or wrong secret name.

**Fix**: In Cloud Run → click your service → **Logs** tab → look for the error message.

---

## 9. Firestore Indexes Required

Your app will show index errors the first time certain queries run.
Each error message contains a direct URL — just click it and create the index.

Here are all indexes you need to create upfront to avoid errors:

### How to create indexes manually:

1. Go to Firebase Console → Firestore Database → **Indexes** tab
2. Click **"Create index"** for each row below:

| Collection | Field 1 | Order | Field 2 | Order |
|---|---|---|---|---|
| `posts` | `uid` | Ascending | `created_at` | Descending |
| `follow_requests` | `to_uid` | Ascending | `status` | Ascending |
| `follow_requests` | `from_uid` | Ascending | `to_uid` | Ascending |
| `users` | `username` | Ascending | | |

> Index creation takes 2-5 minutes. Status changes from "Building" to "Enabled".

---

## Quick Reference

### Local Run
```bash
source .venv/bin/activate   # Mac/Linux
.venv\Scripts\activate      # Windows
python app.py
# Open http://localhost:5000
```

### Redeploy After Code Change
```bash
git add .
git commit -m "your change description"
git push
# Cloud Run auto-deploys in ~3 minutes
```

### View Live Logs
```
GCP Console → Cloud Run → pixelcomm → Logs tab
```

### Update a Secret Value
```
GCP Console → Secret Manager → click secret → Add New Version → paste new value
Then redeploy: Cloud Run → pixelcomm → Edit & Deploy New Revision
```

---

## Architecture Summary

```
GitHub (your code)
    ↓ push triggers auto-build
Cloud Build (builds Python app)
    ↓
Cloud Run (runs your Flask app)
    ↓              ↓              ↓
Firestore     Cloud Storage   Secret Manager
(user data,   (image files)   (API keys,
 posts,                        credentials)
 follows)
```

> All services are in the same GCP project.
> Secret Manager injects secrets as environment variables at runtime.
> No secrets are ever stored in your code or Git repository.
```
