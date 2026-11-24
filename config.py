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
# COLLEGE_NAME is only used to name the university created when an existing
# single-university database is migrated into the platform (see platform_db.py).
COLLEGE_NAME = os.getenv("COLLEGE_NAME", "My University").strip() or "My University"
PLATFORM_LABEL = os.getenv("PLATFORM_LABEL", "Multi-University Platform").strip()
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

# ---- Multi-tenant storage --------------------------------------------------
# One platform database (universities, super admins) plus one isolated SQLite
# database per approved university.
PLATFORM_DB_PATH = Path(os.getenv("PLATFORM_DATABASE_PATH", DATA_DIR / "platform.db"))
TENANT_DIR = Path(os.getenv("TENANT_DIR", DATA_DIR / "tenants"))
TENANT_DIR.mkdir(parents=True, exist_ok=True)

# ---- Turso (hosted libSQL) - keeps data when the host's disk is wiped -------
# TURSO_DATABASE_URL  the PLATFORM database (universities + super admins)
# TURSO_AUTH_TOKEN    token valid for the platform AND every university database
#                     (a "group token"; see README / turso_setup.py)
# TURSO_ORG, TURSO_API_TOKEN, TURSO_GROUP   used to create one Turso database
#                     for each approved university
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()
TURSO_ORG = os.getenv("TURSO_ORG", "").strip()
TURSO_API_TOKEN = os.getenv("TURSO_API_TOKEN", "").strip()
TURSO_GROUP = os.getenv("TURSO_GROUP", "default").strip() or "default"
TURSO_DB_PREFIX = os.getenv("TURSO_DB_PREFIX", "attendease").strip().lower() or "attendease"

TURSO_ENABLED = bool(TURSO_DATABASE_URL)
if TURSO_ENABLED and not TURSO_AUTH_TOKEN:
    # Refuse to fall back silently to local files - on a host with a temporary
    # disk that would lose all data again.
    raise RuntimeError(
        "TURSO_DATABASE_URL is set but TURSO_AUTH_TOKEN is missing. "
        "Add the token or remove TURSO_DATABASE_URL to use local files."
    )

# Where the platform database lives: Turso URL, or a local file.
PLATFORM_TARGET = TURSO_DATABASE_URL if TURSO_ENABLED else PLATFORM_DB_PATH
