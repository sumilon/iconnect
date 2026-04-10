"""
Firebase Admin SDK + Google Cloud Storage initialisation.
Clients are module-level singletons — created once per process.
"""

import json
import os

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud import storage


def _init_firebase_and_gcs():
    """
    Initialise Firebase Admin and return (db, storage_client).
    Two modes:
      1. Cloud Run  → GOOGLE_CREDENTIALS env-var holds the service account JSON.
      2. Local dev  → serviceAccountKey.json file in the project root.
    """
    if os.environ.get("GOOGLE_CREDENTIALS"):
        cred_dict      = json.loads(os.environ["GOOGLE_CREDENTIALS"])
        cred           = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db             = firestore.client()
        storage_client = storage.Client.from_service_account_info(cred_dict)
    else:
        key_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),   # project root
            "serviceAccountKey.json",
        )
        cred           = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred)
        db             = firestore.client()
        storage_client = storage.Client.from_service_account_json(key_path)

    return db, storage_client


db, storage_client = _init_firebase_and_gcs()
