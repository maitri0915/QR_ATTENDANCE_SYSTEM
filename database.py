from pathlib import Path
import sqlite3


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "attendance.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)

    # Return rows that can be accessed by column name.
    conn.row_factory = sqlite3.Row

    # Enforce all foreign-key relationships.
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def init_db() -> None:
    conn = get_connection()

    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,

                role TEXT NOT NULL
                    CHECK (role IN ('admin', 'faculty', 'student')),

                is_active INTEGER NOT NULL DEFAULT 1,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );


            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                code TEXT NOT NULL UNIQUE COLLATE NOCASE
            );


            CREATE TABLE IF NOT EXISTS semesters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                department_id INTEGER NOT NULL,

                number INTEGER NOT NULL
                    CHECK (number BETWEEN 1 AND 8),

                UNIQUE(department_id, number),

                FOREIGN KEY (department_id)
                    REFERENCES departments(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS divisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                department_id INTEGER NOT NULL,
                semester_id INTEGER NOT NULL,

                name TEXT NOT NULL,

                UNIQUE(department_id, semester_id, name),

                FOREIGN KEY (department_id)
                    REFERENCES departments(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (semester_id)
                    REFERENCES semesters(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                department_id INTEGER NOT NULL,
                semester_id INTEGER NOT NULL,

                name TEXT NOT NULL,
                code TEXT NOT NULL,

                UNIQUE(department_id, semester_id, code),

                FOREIGN KEY (department_id)
                    REFERENCES departments(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (semester_id)
                    REFERENCES semesters(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS faculty_profiles (
                user_id INTEGER PRIMARY KEY,

                employee_id TEXT NOT NULL UNIQUE COLLATE NOCASE,

                department_id INTEGER NOT NULL,

                FOREIGN KEY (user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (department_id)
                    REFERENCES departments(id)
                    ON DELETE RESTRICT
            );


            CREATE TABLE IF NOT EXISTS student_profiles (
                user_id INTEGER PRIMARY KEY,

                roll_number TEXT NOT NULL UNIQUE COLLATE NOCASE,

                department_id INTEGER NOT NULL,
                semester_id INTEGER NOT NULL,
                division_id INTEGER NOT NULL,

                FOREIGN KEY (user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (department_id)
                    REFERENCES departments(id)
                    ON DELETE RESTRICT,

                FOREIGN KEY (semester_id)
                    REFERENCES semesters(id)
                    ON DELETE RESTRICT,

                FOREIGN KEY (division_id)
                    REFERENCES divisions(id)
                    ON DELETE RESTRICT
            );


            CREATE TABLE IF NOT EXISTS faculty_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                faculty_user_id INTEGER NOT NULL,
                subject_id INTEGER NOT NULL,
                division_id INTEGER NOT NULL,

                UNIQUE(
                    faculty_user_id,
                    subject_id,
                    division_id
                ),

                FOREIGN KEY (faculty_user_id)
                    REFERENCES faculty_profiles(user_id)
                    ON DELETE CASCADE,

                FOREIGN KEY (subject_id)
                    REFERENCES subjects(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (division_id)
                    REFERENCES divisions(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS attendance_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                faculty_user_id INTEGER NOT NULL,
                subject_id INTEGER NOT NULL,
                division_id INTEGER NOT NULL,

                started_at TEXT NOT NULL,
                closed_at TEXT,

                latitude REAL NOT NULL,
                longitude REAL NOT NULL,

                radius_meters REAL NOT NULL DEFAULT 100,

                is_active INTEGER NOT NULL DEFAULT 1,

                FOREIGN KEY (faculty_user_id)
                    REFERENCES faculty_profiles(user_id)
                    ON DELETE RESTRICT,

                FOREIGN KEY (subject_id)
                    REFERENCES subjects(id)
                    ON DELETE RESTRICT,

                FOREIGN KEY (division_id)
                    REFERENCES divisions(id)
                    ON DELETE RESTRICT
            );


            CREATE TABLE IF NOT EXISTS qr_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                session_id INTEGER NOT NULL,

                token_hash TEXT NOT NULL,

                valid_from TEXT NOT NULL,
                expires_at TEXT NOT NULL,

                FOREIGN KEY (session_id)
                    REFERENCES attendance_sessions(id)
                    ON DELETE CASCADE
            );


            CREATE INDEX IF NOT EXISTS idx_qr_tokens_session_expiry
            ON qr_tokens(session_id, expires_at);


            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                session_id INTEGER NOT NULL,
                student_user_id INTEGER NOT NULL,

                marked_at TEXT NOT NULL,

                status TEXT NOT NULL DEFAULT 'Present'
                    CHECK (status = 'Present'),

                UNIQUE(session_id, student_user_id),

                FOREIGN KEY (session_id)
                    REFERENCES attendance_sessions(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (student_user_id)
                    REFERENCES student_profiles(user_id)
                    ON DELETE RESTRICT
            );


            CREATE TABLE IF NOT EXISTS leave_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                student_user_id INTEGER NOT NULL,
                session_id INTEGER NOT NULL,

                reason TEXT NOT NULL,

                status TEXT NOT NULL DEFAULT 'Pending Leave'
                    CHECK (
                        status IN (
                            'Pending Leave',
                            'Approved Leave',
                            'Rejected Leave'
                        )
                    ),

                submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                reviewed_at TEXT,

                reviewed_by INTEGER,

                FOREIGN KEY (student_user_id)
                    REFERENCES student_profiles(user_id)
                    ON DELETE CASCADE,

                FOREIGN KEY (session_id)
                    REFERENCES attendance_sessions(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (reviewed_by)
                    REFERENCES users(id)
                    ON DELETE SET NULL,

                UNIQUE(student_user_id, session_id)
            );
            """
        )

        conn.commit()

    finally:
        conn.close()