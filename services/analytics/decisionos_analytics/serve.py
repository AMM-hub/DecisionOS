"""Persistent local server entrypoint: uvicorn decisionos_analytics.serve:app"""

from pathlib import Path

from .api import create_app

DATA_DIR = Path(__import__("os").environ.get("DECISIONOS_DATA_DIR", "./var/worker"))
app = create_app(DATA_DIR)
