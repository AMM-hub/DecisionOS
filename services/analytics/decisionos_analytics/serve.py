"""Persistent local server entrypoint: uvicorn decisionos_analytics.serve:app"""

from .api import create_app
from .config import resolve_data_dir

# Absolute, anchored to the package root — the worker resolves the same env var
# through the same helper, so both processes always share one database.
app = create_app(resolve_data_dir())
