
from pathlib import Path
import sqlite3


from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    """Create a configured SQLite database connection."""
    conn = sqlite3.connect(
        DB_PATH,
        timeout=15,
    )

    conn.row_factory = sqlite3.Row

    # Enforce foreign-key constraints on every connection.
    conn.execute("PRAGMA foreign_keys = ON")

    # Allow SQLite to wait briefly when another operation is writing.
    conn.execute("PRAGMA busy_timeout = 15000")

    return conn


def init_db() -> None:
    """Create all database tables and indexes if they do not exist."""
    conn = get_connection()

    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK (is_active IN (0, 1)),
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

                UNIQUE (department_id, number),

                FOREIGN KEY (department_id)
                    REFERENCES departments(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS divisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_id INTEGER NOT NULL,
                semester_id INTEGER NOT NULL,
                name TEXT NOT NULL,

                UNIQUE (department_id, semester_id, name),

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

                UNIQUE (department_id, semester_id, code),

                FOREIGN KEY (department_id)
                    REFERENCES departments(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (semester_id)
                    REFERENCES semesters(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS faculty_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                employee_id TEXT NOT NULL UNIQUE COLLATE NOCASE,
                department_id INTEGER NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK (is_active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (department_id)
                    REFERENCES departments(id)
                    ON DELETE RESTRICT
            );


            CREATE TABLE IF NOT EXISTS student_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                roll_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
                department_id INTEGER NOT NULL,
                semester_id INTEGER NOT NULL,
                division_id INTEGER NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK (is_active IN (0, 1)),
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


            CREATE TABLE IF NOT EXISTS faculty_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                faculty_id INTEGER NOT NULL,
                subject_id INTEGER NOT NULL,
                division_id INTEGER NOT NULL,

                UNIQUE (faculty_id, subject_id, division_id),

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


            CREATE TABLE IF NOT EXISTS timetable (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                division_id INTEGER,
                subject_id INTEGER,
                faculty_id INTEGER,

                day_of_week INTEGER NOT NULL
                    CHECK (day_of_week BETWEEN 0 AND 6),

                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,

                entry_type TEXT NOT NULL DEFAULT 'LECTURE'
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


            CREATE TABLE IF NOT EXISTS college_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                latitude REAL NOT NULL
                    CHECK (latitude BETWEEN -90 AND 90),
                longitude REAL NOT NULL
                    CHECK (longitude BETWEEN -180 AND 180),
                radius_meters REAL NOT NULL DEFAULT 100
                    CHECK (radius_meters > 0)
            );


            CREATE TABLE IF NOT EXISTS attendance_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                faculty_id INTEGER NOT NULL,
                subject_id INTEGER NOT NULL,
                division_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                closed_at TEXT,

                latitude REAL NOT NULL
                    CHECK (latitude BETWEEN -90 AND 90),

                longitude REAL NOT NULL
                    CHECK (longitude BETWEEN -180 AND 180),

                radius_meters REAL NOT NULL DEFAULT 100
                    CHECK (radius_meters > 0),

                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK (is_active IN (0, 1)),

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


            CREATE TABLE IF NOT EXISTS attendance_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,

                status TEXT NOT NULL
                    CHECK (status IN ('present', 'absent')),

                method TEXT NOT NULL,
                marked_at TEXT NOT NULL,
                marked_by INTEGER,

                latitude REAL
                    CHECK (
                        latitude IS NULL
                        OR latitude BETWEEN -90 AND 90
                    ),

                longitude REAL
                    CHECK (
                        longitude IS NULL
                        OR longitude BETWEEN -180 AND 180
                    ),

                distance_m REAL
                    CHECK (distance_m IS NULL OR distance_m >= 0),

                UNIQUE (session_id, student_id),

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


            CREATE TABLE IF NOT EXISTS leave_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                session_id INTEGER,
                timetable_id INTEGER,
                lecture_date TEXT,
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

                UNIQUE (student_id, timetable_id, lecture_date)
            );


            /* Indexes for common lookups and reports. */

            CREATE INDEX IF NOT EXISTS idx_semesters_department
                ON semesters(department_id);

            CREATE INDEX IF NOT EXISTS idx_divisions_department_semester
                ON divisions(department_id, semester_id);

            CREATE INDEX IF NOT EXISTS idx_subjects_department_semester
                ON subjects(department_id, semester_id);

            CREATE INDEX IF NOT EXISTS idx_students_division
                ON student_profiles(division_id);

            CREATE INDEX IF NOT EXISTS idx_students_semester
                ON student_profiles(semester_id);

            CREATE INDEX IF NOT EXISTS idx_faculty_department
                ON faculty_profiles(department_id);

            CREATE INDEX IF NOT EXISTS idx_assignments_faculty
                ON faculty_assignments(faculty_id);

            CREATE INDEX IF NOT EXISTS idx_assignments_subject_division
                ON faculty_assignments(subject_id, division_id);

            CREATE INDEX IF NOT EXISTS idx_timetable_day
                ON timetable(day_of_week);

            CREATE INDEX IF NOT EXISTS idx_timetable_division_day
                ON timetable(division_id, day_of_week);

            CREATE INDEX IF NOT EXISTS idx_timetable_faculty_day
                ON timetable(faculty_id, day_of_week);

            CREATE INDEX IF NOT EXISTS idx_sessions_occurrence
                ON attendance_sessions(timetable_id, lecture_date);

            CREATE INDEX IF NOT EXISTS idx_sessions_division_date
                ON attendance_sessions(division_id, started_at);

            CREATE INDEX IF NOT EXISTS idx_sessions_faculty
                ON attendance_sessions(faculty_id, is_active);

            CREATE INDEX IF NOT EXISTS idx_qr_tokens_session_expiry
                ON qr_tokens(session_id, expires_at);

            CREATE INDEX IF NOT EXISTS idx_attendance_student
                ON attendance_records(student_id, marked_at);

            CREATE INDEX IF NOT EXISTS idx_attendance_session
                ON attendance_records(session_id);

            CREATE INDEX IF NOT EXISTS idx_leave_student_status
                ON leave_requests(student_id, status);

            CREATE INDEX IF NOT EXISTS idx_leave_session
                ON leave_requests(session_id);

            CREATE INDEX IF NOT EXISTS idx_leave_timetable_date
                ON leave_requests(timetable_id, lecture_date);


            /* Prevent multiple active sessions for the same scheduled
               lecture occurrence. Unscheduled sessions remain possible. */

            CREATE UNIQUE INDEX IF NOT EXISTS
                idx_one_active_session_per_occurrence
            ON attendance_sessions(timetable_id, lecture_date)
            WHERE is_active = 1
              AND timetable_id IS NOT NULL
              AND lecture_date IS NOT NULL;
            """
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()