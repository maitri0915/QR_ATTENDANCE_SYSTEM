"""First-time setup.

    python init_db.py            create the database and the first admin account
    python init_db.py --demo     ...and add a sample department, semesters and subjects

The admin account comes from ADMIN_NAME / ADMIN_EMAIL / ADMIN_PASSWORD in `.env`;
if those are not set you will be asked for them.
"""

import getpass
import os
import sys

from auth import hash_password
from database import get_connection, init_db


def admin_exists() -> bool:
    conn = get_connection()
    try:
        return conn.execute("SELECT 1 FROM admins LIMIT 1").fetchone() is not None
    finally:
        conn.close()


def create_admin(name: str, email: str, password: str) -> None:
    email = email.strip().lower()
    if "@" not in email:
        raise ValueError("Enter a valid admin email address.")
    if len(password) < 8:
        raise ValueError("The admin password must have at least 8 characters.")
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO admins (name, email, password_hash, is_active) VALUES (?, ?, ?, 1)",
            (name.strip() or "Administrator", email, hash_password(password)),
        )
        conn.commit()
    finally:
        conn.close()


def ensure_admin_from_env() -> bool:
    """Create the first admin from environment variables, if none exists yet."""
    email = os.getenv("ADMIN_EMAIL", "").strip()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not email or not password or admin_exists():
        return False
    create_admin(os.getenv("ADMIN_NAME", "Administrator"), email, password)
    return True


def prompt_for_admin() -> None:
    print("\nCreate the administrator account")
    name = input("  Full name  : ").strip() or "Administrator"
    email = input("  Email      : ").strip()
    while True:
        password = getpass.getpass("  Password   : ")
        if password == getpass.getpass("  Repeat     : "):
            break
        print("  Passwords do not match, try again.")
    create_admin(name, email, password)
    print("  Admin account created.")


def seed_demo_data() -> None:
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
    init_db()
    print("Database ready.")

    if admin_exists():
        print("An admin account already exists - nothing to create.")
    elif ensure_admin_from_env():
        print("Admin account created from ADMIN_EMAIL / ADMIN_PASSWORD.")
    elif sys.stdin.isatty():
        prompt_for_admin()
    else:
        print("No admin yet. Set ADMIN_EMAIL and ADMIN_PASSWORD in .env and run again.")

    if "--demo" in sys.argv:
        seed_demo_data()


if __name__ == "__main__":
    main()
