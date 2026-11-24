"""Platform-level database: universities, their registration status and the
platform super admins. University data itself lives in one separate SQLite
file per university (see tenancy.py / database.py)."""

import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

import config
import turso_admin
import turso_client
from auth import hash_password
from database import connect, init_db as init_tenant_db
from tenancy import Tenant

STATUSES = ("pending", "approved", "rejected", "suspended")


def get_platform_connection():
    return connect(config.PLATFORM_TARGET)


# On Turso every lookup is a network call, so the per-request university check
# is cached for a few seconds. Suspending takes effect within CACHE_SECONDS.
CACHE_SECONDS = 10
_tenant_cache: dict = {}
_cache_lock = threading.Lock()


def _invalidate_cache() -> None:
    with _cache_lock:
        _tenant_cache.clear()


def init_platform_db() -> None:
    conn = get_platform_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS platform_admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS universities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                address TEXT,
                contact_phone TEXT,
                admin_name TEXT NOT NULL,
                admin_email TEXT NOT NULL COLLATE NOCASE,
                -- Held only until approval, then cleared.
                admin_password_hash TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','approved','rejected','suspended')),
                status_note TEXT,
                db_path TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT,
                reviewed_by INTEGER,
                FOREIGN KEY (reviewed_by) REFERENCES platform_admins(id)
                    ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS platform_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                university_id INTEGER,
                actor_id INTEGER,
                action TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (university_id) REFERENCES universities(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_universities_status
                ON universities(status);
            """
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Platform super admins (never created through a public form)
# ---------------------------------------------------------------------------

def platform_admin_exists() -> bool:
    conn = get_platform_connection()
    try:
        return conn.execute("SELECT 1 FROM platform_admins LIMIT 1").fetchone() is not None
    finally:
        conn.close()


def create_platform_admin(name: str, email: str, password: str) -> None:
    email = email.strip().lower()
    if "@" not in email:
        raise ValueError("Enter a valid email address.")
    if len(password) < 8:
        raise ValueError("The password must have at least 8 characters.")
    conn = get_platform_connection()
    try:
        conn.execute(
            "INSERT INTO platform_admins (name, email, password_hash) VALUES (?, ?, ?)",
            (name.strip() or "Platform Admin", email, hash_password(password)),
        )
        conn.commit()
    finally:
        conn.close()


def get_platform_admin_by_email(email: str) -> Optional[dict]:
    conn = get_platform_connection()
    try:
        row = conn.execute(
            "SELECT id, name, email, password_hash, is_active FROM platform_admins "
            "WHERE email = ? COLLATE NOCASE",
            (email.strip().lower(),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_platform_admin(admin_id: int) -> Optional[dict]:
    conn = get_platform_connection()
    try:
        row = conn.execute(
            "SELECT id, name, email, is_active FROM platform_admins WHERE id = ?",
            (admin_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# University lookup
# ---------------------------------------------------------------------------

def _tenant_path(value: str):
    if turso_client.is_remote(value):
        return value
    path = Path(value)
    return path if path.is_absolute() else config.TENANT_DIR / path


def _row_to_tenant(row) -> Tenant:
    return Tenant(
        id=row["id"], slug=row["slug"], name=row["name"],
        db_path=_tenant_path(row["db_path"]),
    )


def get_active_tenant(slug: str) -> Optional[Tenant]:
    """The university for a slug, only while its status is 'approved'."""
    if not slug:
        return None
    slug = slug.strip().lower()

    if config.TURSO_ENABLED:
        with _cache_lock:
            hit = _tenant_cache.get(slug)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]

    conn = get_platform_connection()
    try:
        row = conn.execute(
            "SELECT id, name, slug, db_path FROM universities "
            "WHERE slug = ? AND status = 'approved' AND db_path IS NOT NULL",
            (slug,),
        ).fetchone()
        tenant = _row_to_tenant(row) if row else None
    finally:
        conn.close()

    if config.TURSO_ENABLED:
        with _cache_lock:
            _tenant_cache[slug] = (time.monotonic(), tenant)
    return tenant


def list_active_tenants() -> list:
    conn = get_platform_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, slug, db_path FROM universities "
            "WHERE status = 'approved' AND db_path IS NOT NULL ORDER BY name"
        ).fetchall()
        return [_row_to_tenant(r) for r in rows]
    finally:
        conn.close()


def get_university(university_id: int) -> Optional[dict]:
    conn = get_platform_connection()
    try:
        row = conn.execute(
            "SELECT * FROM universities WHERE id = ?", (university_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_universities() -> list:
    conn = get_platform_connection()
    try:
        rows = conn.execute(
            """
            SELECT u.*, a.name AS reviewed_by_name
            FROM universities u
            LEFT JOIN platform_admins a ON a.id = u.reviewed_by
            ORDER BY u.created_at DESC, u.id DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def status_counts() -> dict:
    counts = {s: 0 for s in STATUSES}
    conn = get_platform_connection()
    try:
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM universities GROUP BY status"):
            counts[row["status"]] = row["n"]
        return counts
    finally:
        conn.close()


def recent_audit(limit: int = 12) -> list:
    conn = get_platform_connection()
    try:
        rows = conn.execute(
            """
            SELECT l.action, l.note, l.created_at, u.name AS university, a.name AS actor
            FROM platform_audit l
            LEFT JOIN universities u ON u.id = l.university_id
            LEFT JOIN platform_admins a ON a.id = l.actor_id
            ORDER BY l.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def tenant_usage(db_path: Optional[str]) -> dict:
    """Headline counts for the platform overview (read-only, per university)."""
    usage = {"students": None, "faculty": None, "departments": None}
    if not db_path:
        return usage
    path = _tenant_path(db_path)
    if isinstance(path, Path) and not path.exists():
        return usage
    try:
        conn = connect(path)
        try:
            usage["students"] = conn.execute("SELECT COUNT(*) FROM student_profiles").fetchone()[0]
            usage["faculty"] = conn.execute("SELECT COUNT(*) FROM faculty_profiles").fetchone()[0]
            usage["departments"] = conn.execute("SELECT COUNT(*) FROM departments").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        pass
    return usage


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    return slug or "university"


def _unique_slug(conn, name: str) -> str:
    base = slugify(name)
    slug, n = base, 2
    while conn.execute("SELECT 1 FROM universities WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base}-{n}"
        n += 1
    return slug


def register_university(
    name: str, address: str, contact_phone: str,
    admin_name: str, admin_email: str, password: str,
) -> Optional[str]:
    """Store a registration request (status 'pending'). Returns an error
    message, or None on success. Nothing is created for the university until
    a super admin approves the request."""
    name, address = name.strip(), address.strip()
    contact_phone = contact_phone.strip()
    admin_name, admin_email = admin_name.strip(), admin_email.strip().lower()

    if len(name) < 3 or len(name) > 120:
        return "Enter the university's full name (3-120 characters)."
    if len(admin_name) < 2:
        return "Enter the administrator's name."
    if "@" not in admin_email or len(admin_email) > 254:
        return "Enter a valid administrator email address."
    if len(password) < 8:
        return "The password must contain at least 8 characters."

    conn = get_platform_connection()
    try:
        if conn.execute(
            "SELECT 1 FROM universities WHERE name = ? COLLATE NOCASE "
            "AND status != 'rejected'", (name,),
        ).fetchone():
            return "A university with this name is already registered or awaiting approval."
        if conn.execute(
            "SELECT 1 FROM universities WHERE admin_email = ? COLLATE NOCASE "
            "AND status != 'rejected'", (admin_email,),
        ).fetchone():
            return "This email is already used by another university registration."

        slug = _unique_slug(conn, name)
        conn.execute(
            """
            INSERT INTO universities
                (name, slug, address, contact_phone, admin_name, admin_email,
                 admin_password_hash, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (name, slug, address[:300], contact_phone[:30], admin_name,
             admin_email, hash_password(password)),
        )
        conn.commit()
        return None
    finally:
        conn.close()


def registrations_for_email(email: str) -> list:
    conn = get_platform_connection()
    try:
        rows = conn.execute(
            "SELECT name, status, status_note, created_at FROM universities "
            "WHERE admin_email = ? COLLATE NOCASE ORDER BY id DESC",
            (email.strip().lower(),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Super-admin actions
# ---------------------------------------------------------------------------

def _audit(conn, university_id, actor_id, action, note=None):
    conn.execute(
        "INSERT INTO platform_audit (university_id, actor_id, action, note) VALUES (?, ?, ?, ?)",
        (university_id, actor_id, action, note),
    )


def _wait_until_ready(target, tries: int = 20) -> None:
    """A brand-new Turso database can take a few seconds to accept queries."""
    last = None
    for _ in range(tries):
        try:
            c = connect(target)
            try:
                c.execute("SELECT 1").fetchone()
                return
            finally:
                c.close()
        except sqlite3.Error as exc:
            last = exc
            time.sleep(1.5)
    raise sqlite3.OperationalError(f"The new university database did not become ready: {last}")


def approve_university(university_id: int, actor_id: int) -> Optional[str]:
    """Create the university's own database and its first administrator."""
    conn = get_platform_connection()
    db_file = None
    remote_name = None      # set only if THIS call created the Turso database
    try:
        uni = conn.execute("SELECT * FROM universities WHERE id = ?", (university_id,)).fetchone()
        if not uni:
            return "University not found."
        if uni["status"] not in ("pending", "rejected"):
            return "Only pending or rejected requests can be approved."
        if not uni["admin_password_hash"]:
            return "This request has no stored administrator password."

        if config.TURSO_ENABLED:
            try:
                name = turso_admin.database_name(uni["slug"])
                host, created = turso_admin.create_database(name)
            except turso_admin.TursoAdminError as exc:
                return f"Could not create the university's Turso database: {exc}"
            if created:
                remote_name = name
            target = stored = host if host.startswith("http") else f"libsql://{host}"
            _wait_until_ready(target)
        else:
            stored = f"{uni['slug']}.db"
            db_file = config.TENANT_DIR / stored
            if db_file.exists():
                return "A database file for this university already exists; resolve it manually."
            target = db_file

        init_tenant_db(target)
        tconn = connect(target)
        try:
            if config.TURSO_ENABLED and not created:
                if tconn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]:
                    return (f"A Turso database named '{name}' already exists and contains "
                            "data; resolve it manually.")
            tconn.execute(
                "INSERT INTO admins (name, email, password_hash, is_active) VALUES (?, ?, ?, 1)",
                (uni["admin_name"], uni["admin_email"], uni["admin_password_hash"]),
            )
            tconn.commit()
        finally:
            tconn.close()

        conn.execute(
            """
            UPDATE universities
               SET status = 'approved', db_path = ?, admin_password_hash = '',
                   status_note = NULL, reviewed_at = CURRENT_TIMESTAMP, reviewed_by = ?
             WHERE id = ?
            """,
            (stored, actor_id, university_id),
        )
        _audit(conn, university_id, actor_id, "approved")
        conn.commit()
        _invalidate_cache()
        return None
    except Exception:
        conn.rollback()
        if db_file is not None and db_file.exists():
            db_file.unlink()
        if remote_name:
            turso_admin.delete_database(remote_name)
        raise
    finally:
        conn.close()


def _set_status(university_id, actor_id, allowed_from, new_status, action, note=None) -> Optional[str]:
    conn = get_platform_connection()
    try:
        row = conn.execute("SELECT status FROM universities WHERE id = ?", (university_id,)).fetchone()
        if not row:
            return "University not found."
        if row["status"] not in allowed_from:
            return f"A {row['status']} university cannot be {action}."
        conn.execute(
            "UPDATE universities SET status = ?, status_note = ?, reviewed_at = CURRENT_TIMESTAMP, "
            "reviewed_by = ? WHERE id = ?",
            (new_status, (note or "").strip()[:500] or None, actor_id, university_id),
        )
        _audit(conn, university_id, actor_id, action, (note or "").strip()[:500] or None)
        conn.commit()
        _invalidate_cache()
        return None
    finally:
        conn.close()


def reject_university(university_id, actor_id, note=None):
    return _set_status(university_id, actor_id, ("pending",), "rejected", "rejected", note)


def suspend_university(university_id, actor_id, note=None):
    return _set_status(university_id, actor_id, ("approved",), "suspended", "suspended", note)


def activate_university(university_id, actor_id):
    return _set_status(university_id, actor_id, ("suspended",), "approved", "activated")


# ---------------------------------------------------------------------------
# Upgrading an existing single-university installation
# ---------------------------------------------------------------------------

def migrate_legacy_database() -> bool:
    """If this is an installation from before multi-tenancy (one database at
    DB_PATH holding a single university), register that database as the first,
    already-approved university. Nothing is copied or altered."""
    if config.TURSO_ENABLED:
        return False        # local files do not survive on the hosts Turso is used for
    legacy = config.DB_PATH
    if not legacy.exists():
        return False

    conn = get_platform_connection()
    try:
        if conn.execute("SELECT 1 FROM universities LIMIT 1").fetchone():
            return False

        try:
            lconn = connect(legacy)
            try:
                admin = lconn.execute(
                    "SELECT name, email FROM admins ORDER BY id LIMIT 1"
                ).fetchone()
            finally:
                lconn.close()
        except sqlite3.Error:
            return False
        if admin is None:
            return False

        name = config.COLLEGE_NAME
        slug = _unique_slug(conn, name)
        conn.execute(
            """
            INSERT INTO universities
                (name, slug, admin_name, admin_email, status, db_path,
                 status_note, reviewed_at)
            VALUES (?, ?, ?, ?, 'approved', ?, 'Migrated from single-university install',
                    CURRENT_TIMESTAMP)
            """,
            (name, slug, admin["name"], admin["email"], str(legacy.resolve())),
        )
        _audit(conn, conn.execute("SELECT last_insert_rowid()").fetchone()[0], None, "migrated")
        conn.commit()
        return True
    finally:
        conn.close()
