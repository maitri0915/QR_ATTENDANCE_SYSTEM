from pwdlib import PasswordHash

from database import get_connection, init_db


DEMO_ADMIN_EMAIL = "admin@college.local"
DEMO_ADMIN_PASSWORD = "Admin@12345"


def seed_demo_admin() -> None:

    password_hash = PasswordHash.recommended().hash(
        DEMO_ADMIN_PASSWORD
    )

    conn = get_connection()

    try:

        existing = conn.execute(
            """
            SELECT id
            FROM users
            WHERE email = ? COLLATE NOCASE
            """,
            (DEMO_ADMIN_EMAIL,),
        ).fetchone()

        if existing is None:

            conn.execute(
                """
                INSERT INTO users
                (
                    name,
                    email,
                    password_hash,
                    role
                )
                VALUES (?, ?, ?, 'admin')
                """,
                (
                    "Demo Administrator",
                    DEMO_ADMIN_EMAIL,
                    password_hash,
                ),
            )

            conn.commit()

            print("Demo admin created.")

        else:
            print("Demo admin already exists.")

    finally:
        conn.close()


def seed_demo_academic_data() -> None:

    conn = get_connection()

    try:

        # ---------------------------------------------------------
        # Department
        # ---------------------------------------------------------

        conn.execute(
            """
            INSERT OR IGNORE INTO departments
            (
                name,
                code
            )
            VALUES (?, ?)
            """,
            (
                "Computer Engineering",
                "CE",
            ),
        )

        department = conn.execute(
            """
            SELECT id
            FROM departments
            WHERE code = 'CE'
            """
        ).fetchone()

        department_id = department["id"]

        # ---------------------------------------------------------
        # Semesters
        # ---------------------------------------------------------

        for semester_number in range(1, 7):

            conn.execute(
                """
                INSERT OR IGNORE INTO semesters
                (
                    department_id,
                    number
                )
                VALUES (?, ?)
                """,
                (
                    department_id,
                    semester_number,
                ),
            )

        # ---------------------------------------------------------
        # Divisions
        # ---------------------------------------------------------

        semesters = conn.execute(
            """
            SELECT id, number
            FROM semesters
            WHERE department_id = ?
            ORDER BY number
            """,
            (department_id,),
        ).fetchall()

        for semester in semesters:

            for division_name in ("A", "B"):

                conn.execute(
                    """
                    INSERT OR IGNORE INTO divisions
                    (
                        department_id,
                        semester_id,
                        name
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        department_id,
                        semester["id"],
                        division_name,
                    ),
                )

        # ---------------------------------------------------------
        # Demo subjects
        # ---------------------------------------------------------

        semester_5 = conn.execute(
            """
            SELECT id
            FROM semesters
            WHERE department_id = ?
              AND number = 5
            """,
            (department_id,),
        ).fetchone()

        semester_5_id = semester_5["id"]

        subjects = [
            (
                "Web Development using Python",
                "WDPY",
            ),
            (
                "Information Security",
                "IS",
            ),
            (
                "Internet of Things",
                "IOT",
            ),
            (
                "Cyber and Hardware Security",
                "CHASM",
            ),
        ]

        for subject_name, subject_code in subjects:

            conn.execute(
                """
                INSERT OR IGNORE INTO subjects
                (
                    department_id,
                    semester_id,
                    name,
                    code
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    department_id,
                    semester_5_id,
                    subject_name,
                    subject_code,
                ),
            )

        conn.commit()

        print("Demo academic data created.")

    finally:
        conn.close()


if __name__ == "__main__":

    init_db()

    seed_demo_admin()

    seed_demo_academic_data()

    print("Database initialization complete.")