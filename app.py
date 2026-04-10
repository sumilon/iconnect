"""
Entry-point for local development and Cloud Run.

Cloud Run:  gunicorn -w 2 -b :$PORT "app:app"
Local:      python app.py   (or flask --app app run --debug)
"""

import os

from core import create_app

app = create_app()

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "development") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)

