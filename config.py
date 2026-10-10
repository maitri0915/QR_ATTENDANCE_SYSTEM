"""Central configuration. Everything a deployer may want to change lives here
and is read from environment variables (or a local `.env` file)."""

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---- Branding (shown across the site) -------------------------------------
APP_NAME = os.getenv("APP_NAME", "AttendEase").strip() or "AttendEase"
COLLEGE_NAME = os.getenv("COLLEGE_NAME", "Your College").strip() or "Your College"
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "").strip()

# ---- Security -------------------------------------------------------------
COOKIE_HTTPS_ONLY = os.getenv("COOKIE_HTTPS_ONLY", "0").strip().lower() in {
    "1", "true", "yes",
}


def _load_secret_key() -> str:
    """Use SESSION_SECRET_KEY if set; otherwise create one once and keep it
    on disk so logins survive restarts."""
    key = os.getenv("SESSION_SECRET_KEY", "").strip()
    if key:
        return key
    key_file = DATA_DIR / "secret_key"
    if key_file.exists():
        existing = key_file.read_text().strip()
        if existing:
            return existing
    key = secrets.token_urlsafe(48)
    key_file.write_text(key)
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return key


SECRET_KEY = _load_secret_key()

# ---- Database -------------------------------------------------------------
DB_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "attendance.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
