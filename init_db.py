"""First-time setup for the multi-university platform.

    python init_db.py                    create the platform database and the first
                                         platform super admin
    python init_db.py --demo             ...and an approved "Demo University" with
                                         a sample department, semesters and subjects

The super admin comes from PLATFORM_ADMIN_NAME / PLATFORM_ADMIN_EMAIL /
PLATFORM_ADMIN_PASSWORD in `.env`; if those are not set you are asked for them.
Super admins can only be created here (or via .env) - never from a web form.

Universities register themselves at /register-university and are approved by
the super admin. An existing single-university database (data/attendance.db) is
registered automatically as the first university on startup.
"""

import getpass
import os
import sys

import platform_db
from database import get_connection, init_db
from tenancy import use_tenant


def ensure_platform_admin_from_env() -> bool:
    """Create the first super admin from the environment, if none exists yet."""
    email = os.getenv("PLATFORM_ADMIN_EMAIL", "").strip()
    password = os.getenv("PLATFORM_ADMIN_PASSWORD", "")
    if not email or not password or platform_db.platform_admin_exists():
        return False
    platform_db.create_platform_admin(
        os.getenv("PLATFORM_ADMIN_NAME", "Platform Admin"), email, password
    )
    return True


def prompt_for_platform_admin() -> None:
    print("\nCreate the platform super admin account")
    name = input("  Full name  : ").strip() or "Platform Admin"
    email = input("  Email      : ").strip()
    while True:
        password = getpass.getpass("  Password   : ")
        if password == getpass.getpass("  Repeat     : "):
            break
        print("  Passwords do not match, try again.")
    platform_db.create_platform_admin(name, email, password)
    print("  Super admin created.")


def seed_demo_university() -> None:
    """Create an already-approved demo university with sample academic data."""
    admin_email = os.getenv("DEMO_ADMIN_EMAIL", "admin@demo.edu")
    admin_password = os.getenv("DEMO_ADMIN_PASSWORD", "demo-password-1")

    error = platform_db.register_university(
        "Demo University", "", "", "Demo Admin", admin_email, admin_password
    )
    if error and "already" not in error:
        raise ValueError(error)

    demo = next(
        (u for u in platform_db.list_universities() if u["name"] == "Demo University"),
        None,
    )
    if demo is None:
        return
    if demo["status"] == "pending":
        actor = None
        conn = platform_db.get_platform_connection()
        try:
            row = conn.execute("SELECT id FROM platform_admins ORDER BY id LIMIT 1").fetchone()
            actor = row["id"] if row else None
        finally:
            conn.close()
        err = platform_db.approve_university(demo["id"], actor)
        if err:
            raise ValueError(err)
        demo = platform_db.get_university(demo["id"])

    tenant = platform_db.get_active_tenant(demo["slug"])
    if tenant is None:
        return
    with use_tenant(tenant):
        seed_demo_data()
    print(f"Demo university ready: slug '{tenant.slug}', admin {admin_email}.")


def seed_demo_data() -> None:
    """Sample academic data for the CURRENT university."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO departments (name, code) VALUES (?, ?)",
            ("Computer Engineering", "CE"),
        )
        dep = conn.execute("SELECT id FROM departments WHERE code = 'CE'").fetchone()["id"]
        for number in range(1, 7):
            conn.execute(
                "INSERT OR IGNORE INTO semesters (department_id, number) VALUES (?, ?)",
                (dep, number),
            )
        for sem in conn.execute(
            "SELECT id, number FROM semesters WHERE department_id = ?", (dep,)
        ).fetchall():
            for division in ("A", "B"):
                conn.execute(
                    "INSERT OR IGNORE INTO divisions (department_id, semester_id, name) VALUES (?, ?, ?)",
                    (dep, sem["id"], division),
                )
            if sem["number"] == 5:
                for subject, code in [
                    ("Web Development using Python", "WDPY"),
                    ("Information Security", "IS"),
                    ("Internet of Things", "IOT"),
                    ("Cyber and Hardware Security", "CHASM"),
                ]:
                    conn.execute(
                        "INSERT OR IGNORE INTO subjects (department_id, semester_id, name, code) VALUES (?, ?, ?, ?)",
                        (dep, sem["id"], subject, code),
                    )
        conn.commit()
        print("Sample academic data added.")
    finally:
        conn.close()


def main() -> None:
    platform_db.init_platform_db()
    print("Platform database ready.")

    if platform_db.platform_admin_exists():
        print("A platform super admin already exists - nothing to create.")
    elif ensure_platform_admin_from_env():
        print("Platform super admin created from PLATFORM_ADMIN_EMAIL / PLATFORM_ADMIN_PASSWORD.")
    elif sys.stdin.isatty():
        prompt_for_platform_admin()
    else:
        print("No super admin yet. Set PLATFORM_ADMIN_EMAIL and PLATFORM_ADMIN_PASSWORD in .env and run again.")

    if platform_db.migrate_legacy_database():
        print("Existing single-university database registered as the first university.")

    if "--demo" in sys.argv:
        seed_demo_university()


if __name__ == "__main__":
    main()
