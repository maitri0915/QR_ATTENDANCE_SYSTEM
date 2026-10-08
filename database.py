from pathlib import Path
import sqlite3


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "attendance.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)

    # Return rows that can be accessed by column name.
    conn.row_factory = sqlite3.Row

    # Enforce foreign-key relationships.
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def init_db() -> None:
    conn = get_connection()

    try:
        conn.executescript(
            """

            /* =========================================================
               ADMIN
               ========================================================= */

            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT NOT NULL,

                email TEXT NOT NULL
                    UNIQUE COLLATE NOCASE,

                password_hash TEXT NOT NULL,

                is_active INTEGER NOT NULL DEFAULT 1,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );


            /* =========================================================
               DEPARTMENT
               ========================================================= */

            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT NOT NULL UNIQUE,

                code TEXT NOT NULL
                    UNIQUE COLLATE NOCASE
            );


            /* =========================================================
               SEMESTER
               ========================================================= */

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


            /* =========================================================
               DIVISION
               ========================================================= */

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


            /* =========================================================
               SUBJECT
               ========================================================= */

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


            /* =========================================================
               FACULTY
               ========================================================= */

            CREATE TABLE IF NOT EXISTS faculty_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT NOT NULL,

                email TEXT NOT NULL
                    UNIQUE COLLATE NOCASE,

                password_hash TEXT NOT NULL,

                employee_id TEXT NOT NULL
                    UNIQUE COLLATE NOCASE,

                department_id INTEGER NOT NULL,

                is_active INTEGER NOT NULL DEFAULT 1,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (department_id)
                    REFERENCES departments(id)
                    ON DELETE RESTRICT
            );


            /* =========================================================
               STUDENT
               ========================================================= */

            CREATE TABLE IF NOT EXISTS student_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT NOT NULL,

                email TEXT NOT NULL
                    UNIQUE COLLATE NOCASE,

                password_hash TEXT NOT NULL,

                roll_number TEXT NOT NULL
                    UNIQUE COLLATE NOCASE,

                department_id INTEGER NOT NULL,

                semester_id INTEGER NOT NULL,

                division_id INTEGER NOT NULL,

                is_active INTEGER NOT NULL DEFAULT 1,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

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


            /* =========================================================
               FACULTY ASSIGNMENT
               ========================================================= */

            CREATE TABLE IF NOT EXISTS faculty_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                faculty_id INTEGER NOT NULL,

                subject_id INTEGER NOT NULL,

                division_id INTEGER NOT NULL,

                UNIQUE(
                    faculty_id,
                    subject_id,
                    division_id
                ),

                FOREIGN KEY (faculty_id)
                    REFERENCES faculty_profiles(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (subject_id)
                    REFERENCES subjects(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (division_id)
                    REFERENCES divisions(id)
                    ON DELETE CASCADE
            );


            /* =========================================================
               TIMETABLE
               ========================================================= */

            CREATE TABLE IF NOT EXISTS timetable (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                division_id INTEGER,

                subject_id INTEGER,

                faculty_id INTEGER,

                day_of_week INTEGER NOT NULL
                    CHECK (day_of_week BETWEEN 0 AND 6),

                start_time TEXT NOT NULL,

                end_time TEXT NOT NULL,

                entry_type TEXT NOT NULL
                    DEFAULT 'LECTURE'
                    CHECK (
                        entry_type IN (
                            'LECTURE',
                            'LAB',
                            'HOD_USE',
                            'OTHER'
                        )
                    ),

                title TEXT,

                FOREIGN KEY (division_id)
                    REFERENCES divisions(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (subject_id)
                    REFERENCES subjects(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (faculty_id)
                    REFERENCES faculty_profiles(id)
                    ON DELETE SET NULL
            );


            CREATE INDEX IF NOT EXISTS idx_timetable_day
            ON timetable(day_of_week);


            /* =========================================================
               COLLEGE ATTENDANCE LOCATION
               ========================================================= */

            CREATE TABLE IF NOT EXISTS college_settings (
                id INTEGER PRIMARY KEY
                    CHECK (id = 1),

                latitude REAL NOT NULL,

                longitude REAL NOT NULL,

                radius_meters REAL NOT NULL
                    DEFAULT 100
            );


            /* =========================================================
               ATTENDANCE SESSION
               ========================================================= */

            CREATE TABLE IF NOT EXISTS attendance_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                faculty_id INTEGER NOT NULL,

                subject_id INTEGER NOT NULL,

                division_id INTEGER NOT NULL,

                started_at TEXT NOT NULL,

                closed_at TEXT,

                latitude REAL NOT NULL,

                longitude REAL NOT NULL,

                radius_meters REAL NOT NULL
                    DEFAULT 100,

                is_active INTEGER NOT NULL
                    DEFAULT 1,

                timetable_id INTEGER,

                lecture_date TEXT,

                FOREIGN KEY (faculty_id)
                    REFERENCES faculty_profiles(id)
                    ON DELETE RESTRICT,

                FOREIGN KEY (subject_id)
                    REFERENCES subjects(id)
                    ON DELETE RESTRICT,

                FOREIGN KEY (division_id)
                    REFERENCES divisions(id)
                    ON DELETE RESTRICT,

                FOREIGN KEY (timetable_id)
                    REFERENCES timetable(id)
                    ON DELETE SET NULL
            );


            CREATE INDEX IF NOT EXISTS idx_attendance_session_occurrence
            ON attendance_sessions(timetable_id, lecture_date);


            /* =========================================================
               QR TOKEN
               ========================================================= */

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


            /* =========================================================
               ATTENDANCE RECORD
               ========================================================= */

            CREATE TABLE IF NOT EXISTS attendance_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                session_id INTEGER NOT NULL,

                student_id INTEGER NOT NULL,

                status TEXT NOT NULL
                    CHECK (status IN ('present', 'absent')),

                method TEXT NOT NULL,

                marked_at TEXT NOT NULL,

                marked_by INTEGER,

                latitude REAL,

                longitude REAL,

                distance_m REAL,

                UNIQUE(session_id, student_id),

                FOREIGN KEY (session_id)
                    REFERENCES attendance_sessions(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (student_id)
                    REFERENCES student_profiles(id)
                    ON DELETE RESTRICT,

                FOREIGN KEY (marked_by)
                    REFERENCES faculty_profiles(id)
                    ON DELETE SET NULL
            );


            /* =========================================================
               LEAVE REQUEST
               ========================================================= */

            CREATE TABLE IF NOT EXISTS leave_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                student_id INTEGER NOT NULL,

                session_id INTEGER,

                timetable_id INTEGER,

                lecture_date TEXT,

                reason TEXT NOT NULL,

                status TEXT NOT NULL
                    DEFAULT 'Pending Leave'
                    CHECK (
                        status IN (
                            'Pending Leave',
                            'Approved Leave',
                            'Rejected Leave'
                        )
                    ),

                submitted_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                reviewed_at TEXT,

                reviewed_by INTEGER,

                FOREIGN KEY (student_id)
                    REFERENCES student_profiles(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (session_id)
                    REFERENCES attendance_sessions(id)
                    ON DELETE SET NULL,

                FOREIGN KEY (timetable_id)
                    REFERENCES timetable(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (reviewed_by)
                    REFERENCES faculty_profiles(id)
                    ON DELETE SET NULL,

                UNIQUE(
                    student_id,
                    timetable_id,
                    lecture_date
                )
            );

            """
        )

        conn.commit()

    finally:
        conn.close()