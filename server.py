"""Entry point — run with: uvicorn server:app --reload"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.main import app  # noqa: F401
