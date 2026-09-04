"""Filesystem anchors so the backend works from any working directory."""

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BACKEND_DIR / "templates"
RAW_DATA_DIR = BACKEND_DIR / "raw_data"
TMP_DIR = BACKEND_DIR / "tmp"
