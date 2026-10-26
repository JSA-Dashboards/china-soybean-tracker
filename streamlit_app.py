"""Streamlit Cloud entry point for the standalone app: the real page is app.py (the admin portal mirrors that name)."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
