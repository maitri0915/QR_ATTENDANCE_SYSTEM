from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from auth import get_current_user
from database import get_connection

from datetime import datetime, timedelta
import secrets
import hashlib
import base64
import io
import qrcode


router = APIRouter()
templates = Jinja2Templates(directory="templates")

QR_VALIDITY_SECONDS = 30
ATTENDANCE_RADIUS_METERS = 100


# ============================================================
# FACULTY AUTH
# ============================================================

def require_faculty(request: Request):
    user = get_current_user(request)

    if not user:
        return None

    if user["role"] != "faculty":
        return None

    return user


# ============================================================
# ATTENDANCE TABLES
# ============================================================

def ensure_attendance_tables(conn):
    conn.execute("""
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
            is_active INTEGER NOT NULL DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS qr_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL,
            valid_from TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            student_user_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            method TEXT NOT NULL,
            marked_at TEXT NOT NULL,
            marked_by INTEGER,
            latitude REAL,
            longitude REAL,
            distance_m REAL
        )
    """)

    conn.commit()

def get_today_timetable_entry(
    conn,
    timetable_id,
    faculty_user_id
):
    today = datetime.now()

    entry = conn.execute(
        """
        SELECT
            t.id,
            t.day_of_week,
            t.start_time,
            t.end_time,
            t.entry_type,
            t.subject_id,
            t.division_id,
            t.faculty_user_id,
            s.name AS subject_name,
            s.code AS subject_code,
            d.name AS division_name
        FROM timetable t

        JOIN subjects s
            ON s.id = t.subject_id

        JOIN divisions d
            ON d.id = t.division_id

        WHERE t.id = ?
        AND t.faculty_user_id = ?
        AND t.entry_type IN ('LECTURE', 'LAB')
        """,
        (
            timetable_id,
            faculty_user_id
        )
    ).fetchone()

    if not entry:
        return None, "Timetable lecture not found."

    if entry["day_of_week"] != today.weekday():
        return None, "This lecture is not scheduled for today."

    return entry, None

# ============================================================
# FACULTY DASHBOARD
# ============================================================

@router.get("/faculty/dashboard", response_class=HTMLResponse)
def faculty_dashboard(request: Request):

    user = require_faculty(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    conn = get_connection()

    faculty = conn.execute(
        """
        SELECT
            fp.user_id,
            fp.employee_id,
            fp.department_id,
            d.name AS department_name,
            d.code AS department_code,
            u.name AS faculty_name,
            u.email
        FROM faculty_profiles fp
        JOIN users u ON u.id = fp.user_id
        JOIN departments d ON d.id = fp.department_id
        WHERE fp.user_id = ?
        """,
        (user["id"],)
    ).fetchone()

    assignments = conn.execute(
        """
        SELECT
            fa.id AS assignment_id,
            s.id AS subject_id,
            s.name AS subject_name,
            s.code AS subject_code,
            d.id AS division_id,
            d.name AS division_name,
            sem.number AS semester_number,
            dept.name AS department_name,
            dept.code AS department_code,

            (
                SELECT COUNT(*)
                FROM student_profiles sp
                WHERE sp.division_id = d.id
            ) AS student_count

        FROM faculty_assignments fa

        JOIN subjects s
            ON s.id = fa.subject_id

        JOIN divisions d
            ON d.id = fa.division_id

        JOIN semesters sem
            ON sem.id = d.semester_id

        JOIN departments dept
            ON dept.id = d.department_id

        WHERE fa.faculty_user_id = ?

        ORDER BY sem.number, d.name, s.name
        """,
        (user["id"],)
    ).fetchall()

    conn.close()

    return templates.TemplateResponse(
        "faculty_dashboard.html",
        {
            "request": request,
            "user": user,
            "faculty": faculty,
            "assignments": assignments
        }
    )


# ============================================================
# FACULTY ASSIGNMENT / CLASS
# ============================================================

@router.get(
    "/faculty/assignments/{assignment_id}",
    response_class=HTMLResponse
)
def faculty_assignment(request: Request, assignment_id: int):

    user = require_faculty(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    conn = get_connection()

    assignment = conn.execute(
        """
        SELECT
            fa.id AS assignment_id,
            s.id AS subject_id,
            s.name AS subject_name,
            s.code AS subject_code,
            d.id AS division_id,
            d.name AS division_name,
            sem.number AS semester_number,
            dept.name AS department_name,
            dept.code AS department_code

        FROM faculty_assignments fa

        JOIN subjects s
            ON s.id = fa.subject_id

        JOIN divisions d
            ON d.id = fa.division_id

        JOIN semesters sem
            ON sem.id = d.semester_id

        JOIN departments dept
            ON dept.id = d.department_id

        WHERE fa.id = ?
        AND fa.faculty_user_id = ?
        """,
        (assignment_id, user["id"])
    ).fetchone()

    if not assignment:
        conn.close()

        return HTMLResponse(
            "<h2>Assignment not found or not assigned to you.</h2>",
            status_code=404
        )

    students = conn.execute(
        """
        SELECT
            sp.user_id,
            sp.roll_number,
            u.name,
            u.email

        FROM student_profiles sp

        JOIN users u
            ON u.id = sp.user_id

        WHERE sp.division_id = ?

        ORDER BY sp.roll_number
        """,
        (assignment["division_id"],)
    ).fetchall()

    conn.close()

    return templates.TemplateResponse(
        "faculty_assignment.html",
        {
            "request": request,
            "user": user,
            "assignment": assignment,
            "students": students
        }
    )


# ============================================================
# START ATTENDANCE PAGE
# ============================================================

@router.get(
    "/faculty/assignments/{assignment_id}/start",
    response_class=HTMLResponse
)
def start_attendance_page(request: Request, assignment_id: int):

    user = require_faculty(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    conn = get_connection()

    assignment = conn.execute(
        """
        SELECT
            fa.id AS assignment_id,
            s.id AS subject_id,
            s.name AS subject_name,
            s.code AS subject_code,
            d.id AS division_id,
            d.name AS division_name,
            sem.number AS semester_number

        FROM faculty_assignments fa

        JOIN subjects s
            ON s.id = fa.subject_id

        JOIN divisions d
            ON d.id = fa.division_id

        JOIN semesters sem
            ON sem.id = d.semester_id

        WHERE fa.id = ?
        AND fa.faculty_user_id = ?
        """,
        (assignment_id, user["id"])
    ).fetchone()

    conn.close()

    if not assignment:
        return HTMLResponse(
            "<h2>Assignment not found.</h2>",
            status_code=404
        )

    return templates.TemplateResponse(
        "faculty_start_session.html",
        {
            "request": request,
            "user": user,
            "assignment": assignment
        }
    )

@router.get("/faculty/timetable", response_class=HTMLResponse)
def faculty_timetable(request: Request):
    faculty = require_faculty(request)

    if not faculty:
        return RedirectResponse("/login", status_code=303)


    conn = get_connection()
    try:
        timetable = conn.execute(
            """
            SELECT
                timetable.id,
                timetable.day_of_week,
                timetable.start_time,
                timetable.end_time,
                timetable.entry_type,
                timetable.title,
                subjects.name AS subject_name,
                subjects.code AS subject_code,
                divisions.name AS division_name,
                semesters.number AS semester_number,
                departments.code AS department_code
            FROM timetable
            LEFT JOIN subjects
                ON subjects.id = timetable.subject_id
            LEFT JOIN divisions
                ON divisions.id = timetable.division_id
            LEFT JOIN semesters
                ON semesters.id = divisions.semester_id
            LEFT JOIN departments
                ON departments.id = divisions.department_id
            WHERE timetable.faculty_user_id = ?
               OR timetable.entry_type IN ('HOD_USE', 'OTHER')
            ORDER BY timetable.day_of_week, timetable.start_time
            """,
            (faculty["id"],),
        ).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(
        "faculty_timetable.html",
        {
            "request": request,
            "current_user": faculty,
            "timetable": timetable,
        },
    )
# ============================================================
# CREATE ATTENDANCE SESSION
# ============================================================

@router.post("/api/faculty/sessions")
async def create_session(request: Request):

    user = require_faculty(request)

    if not user:
        return JSONResponse(
            {"error": "Faculty login required."},
            status_code=401
        )

    try:
        data = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Invalid request data."},
            status_code=400
        )

    assignment_id = data.get("assignment_id")
    timetable_id = data.get("timetable_id")
    lecture_date = data.get("lecture_date")

    if assignment_id is None:
        return JSONResponse(
            {"error": "Assignment is required."},
            status_code=400
        )

    if timetable_id is None or lecture_date is None:
        return JSONResponse(
            {"error": "Timetable lecture and date are required."},
            status_code=400
        )

    try:
        assignment_id = int(assignment_id)
        timetable_id = int(timetable_id)

        # Validate date format
        datetime.strptime(
            str(lecture_date),
            "%Y-%m-%d"
        )

    except (TypeError, ValueError):
        return JSONResponse(
            {"error": "Invalid assignment, timetable, date, or location."},
            status_code=400
        )

    conn = get_connection()

    ensure_attendance_tables(conn)

    college_location = conn.execute(
        """
        SELECT latitude, longitude, radius_meters
        FROM college_settings
        WHERE id = 1
        """
    ).fetchone()

    if not college_location:
        conn.close()

        return JSONResponse(
            {
                "error": "College attendance location has not been configured by Admin."
            },
            status_code=400
        )

    # --------------------------------------------------------
    # Verify faculty assignment
    # --------------------------------------------------------

    assignment = conn.execute(
        """
        SELECT
            id,
            subject_id,
            division_id
        FROM faculty_assignments
        WHERE id = ?
        AND faculty_user_id = ?
        """,
        (
            assignment_id,
            user["id"]
        )
    ).fetchone()

    if not assignment:
        conn.close()

        return JSONResponse(
            {"error": "You are not assigned to this class."},
            status_code=403
        )

    # --------------------------------------------------------
    # Verify timetable entry
    # --------------------------------------------------------

    timetable = conn.execute(
        """
        SELECT
            id,
            day_of_week,
            start_time,
            end_time,
            entry_type,
            subject_id,
            division_id,
            faculty_user_id
        FROM timetable
        WHERE id = ?
        """,
        (timetable_id,)
    ).fetchone()

    if not timetable:
        conn.close()

        return JSONResponse(
            {"error": "Timetable lecture not found."},
            status_code=404
        )

    # Attendance is allowed only for lectures/labs.
    if timetable["entry_type"] not in ("LECTURE", "LAB"):
        conn.close()

        return JSONResponse(
            {
                "error": "Attendance cannot be started for this timetable entry."
            },
            status_code=400
        )

    # --------------------------------------------------------
    # Make sure timetable matches faculty assignment
    # --------------------------------------------------------

    if (
        timetable["subject_id"] != assignment["subject_id"]
        or timetable["division_id"] != assignment["division_id"]
        or timetable["faculty_user_id"] != user["id"]
    ):
        conn.close()

        return JSONResponse(
            {
                "error": "This timetable lecture is not assigned to you."
            },
            status_code=403
        )

    # --------------------------------------------------------
    # Verify lecture date matches timetable day
    # --------------------------------------------------------

    lecture_dt = datetime.strptime(
        str(lecture_date),
        "%Y-%m-%d"
    )

    # Python weekday:
    # Monday = 0
    # Sunday = 6

    if lecture_dt.weekday() != timetable["day_of_week"]:
        conn.close()

        return JSONResponse(
            {
                "error": "The selected date does not match the timetable day."
            },
            status_code=400
        )

    # --------------------------------------------------------
    # Prevent duplicate attendance session
    # for the same timetable occurrence
    # --------------------------------------------------------

    existing = conn.execute(
        """
        SELECT id, is_active
        FROM attendance_sessions
        WHERE timetable_id = ?
        AND lecture_date = ?
        """,
        (
            timetable_id,
            lecture_date
        )
    ).fetchone()

    if existing:

        conn.close()

        if existing["is_active"] == 1:
            return JSONResponse(
                {
                    "error": "Attendance is already active for this lecture.",
                    "session_id": existing["id"]
                },
                status_code=409
            )

        return JSONResponse(
            {
                "error": "Attendance has already been completed for this lecture.",
                "session_id": existing["id"]
            },
            status_code=409
        )

    # --------------------------------------------------------
    # Create attendance session
    # --------------------------------------------------------

    now = datetime.now()
    now_text = now.isoformat(timespec="seconds")

    cursor = conn.execute(
        """
        INSERT INTO attendance_sessions
        (
            faculty_user_id,
            subject_id,
            division_id,
            started_at,
            latitude,
            longitude,
            radius_meters,
            is_active,
            timetable_id,
            lecture_date
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            user["id"],
            assignment["subject_id"],
            assignment["division_id"],
            now_text,
            college_location["latitude"],
            college_location["longitude"],
            college_location["radius_meters"],
            timetable_id,
            lecture_date
        )
    )

    session_id = cursor.lastrowid

    # --------------------------------------------------------
    # Create first QR token
    # --------------------------------------------------------

    token = secrets.token_urlsafe(16)

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    expires = now + timedelta(
        seconds=QR_VALIDITY_SECONDS
    )

    conn.execute(
        """
        INSERT INTO qr_tokens
        (
            session_id,
            token_hash,
            valid_from,
            expires_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            session_id,
            token_hash,
            now_text,
            expires.isoformat(timespec="seconds")
        )
    )

    conn.commit()
    conn.close()

    return JSONResponse(
        {
            "success": True,
            "session_id": session_id,
            "timetable_id": timetable_id,
            "lecture_date": lecture_date
        }
    )

# ============================================================
# LIVE ATTENDANCE PAGE
# ============================================================

@router.get(
    "/faculty/sessions/{session_id}/live",
    response_class=HTMLResponse
)
def live_session_page(request: Request, session_id: int):

    user = require_faculty(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    conn = get_connection()

    session = conn.execute(
        """
        SELECT
            a.id,
            a.is_active,
            a.started_at,
            a.subject_id,
            a.division_id,

            s.name AS subject_name,
            s.code AS subject_code,

            d.name AS division_name,
            sem.number AS semester_number

        FROM attendance_sessions a

        JOIN subjects s
            ON s.id = a.subject_id

        JOIN divisions d
            ON d.id = a.division_id

        JOIN semesters sem
            ON sem.id = d.semester_id

        WHERE a.id = ?
        AND a.faculty_user_id = ?
        """,
        (session_id, user["id"])
    ).fetchone()

    conn.close()

    if not session:
        return HTMLResponse(
            "<h2>Attendance session not found.</h2>",
            status_code=404
        )

    return templates.TemplateResponse(
        "faculty_session_live.html",
        {
            "request": request,
            "user": user,
            "session": session
        }
    )


# ============================================================
# GET CURRENT QR
# ============================================================

@router.get("/api/faculty/sessions/{session_id}/qr")
def get_qr(request: Request, session_id: int):

    user = require_faculty(request)

    if not user:
        return JSONResponse(
            {"error": "Faculty login required."},
            status_code=401
        )

    conn = get_connection()

    session = conn.execute(
        """
        SELECT *
        FROM attendance_sessions
        WHERE id = ?
        AND faculty_user_id = ?
        """,
        (session_id, user["id"])
    ).fetchone()

    if not session:
        conn.close()

        return JSONResponse(
            {"error": "Session not found."},
            status_code=404
        )

    if session["is_active"] != 1:
        conn.close()

        return JSONResponse(
            {"error": "Session is closed."},
            status_code=400
        )

    now = datetime.now()

    token = secrets.token_urlsafe(16)

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    expires = now + timedelta(
        seconds=QR_VALIDITY_SECONDS
    )

    conn.execute(
        """
        INSERT INTO qr_tokens
        (
            session_id,
            token_hash,
            valid_from,
            expires_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            session_id,
            token_hash,
            now.isoformat(timespec="seconds"),
            expires.isoformat(timespec="seconds")
        )
    )

    conn.commit()

    qr = qrcode.QRCode(
        version=1,
        box_size=8,
        border=4
    )

    qr.add_data(token)
    qr.make(fit=True)

    image = qr.make_image()

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    qr_base64 = base64.b64encode(
        buffer.getvalue()
    ).decode("utf-8")

    present = conn.execute(
        """
        SELECT
            ar.student_user_id,
            sp.roll_number,
            u.name,
            ar.marked_at

        FROM attendance_records ar

        JOIN student_profiles sp
            ON sp.user_id = ar.student_user_id

        JOIN users u
            ON u.id = ar.student_user_id

        WHERE ar.session_id = ?
        AND ar.status = 'present'

        ORDER BY sp.roll_number
        """,
        (session_id,)
    ).fetchall()

    conn.close()

    return JSONResponse(
        {
            "token": token,
            "seconds_left": QR_VALIDITY_SECONDS,
            "qr_image": qr_base64,
            "present_count": len(present),
            "present_students": [
                {
                    "roll_number": row["roll_number"],
                    "name": row["name"],
                    "marked_at": row["marked_at"]
                }
                for row in present
            ]
        }
    )


# ============================================================
# LIVE ATTENDANCE LIST
# ============================================================

@router.get("/api/faculty/sessions/{session_id}/attendance")
def live_attendance(request: Request, session_id: int):

    user = require_faculty(request)

    if not user:
        return JSONResponse(
            {"error": "Faculty login required."},
            status_code=401
        )

    conn = get_connection()

    try:
        session = conn.execute(
            """
            SELECT id, division_id, is_active
            FROM attendance_sessions
            WHERE id = ?
            AND faculty_user_id = ?
            """,
            (session_id, user["id"])
        ).fetchone()

        if not session:
            return JSONResponse(
                {"error": "Session not found."},
                status_code=404
            )

        present = conn.execute(
            """
            SELECT
                sp.roll_number,
                u.name,
                ar.marked_at
            FROM attendance_records ar
            JOIN student_profiles sp
                ON sp.user_id = ar.student_user_id
            JOIN users u
                ON u.id = ar.student_user_id
            WHERE ar.session_id = ?
            AND ar.status = 'present'
            ORDER BY sp.roll_number
            """,
            (session_id,)
        ).fetchall()

        total = conn.execute(
            "SELECT COUNT(*) FROM student_profiles WHERE division_id = ?",
            (session["division_id"],)
        ).fetchone()[0]

    finally:
        conn.close()

    return JSONResponse(
        {
            "is_active": session["is_active"] == 1,
            "present_count": len(present),
            "total_students": total,
            "present_students": [
                {
                    "roll_number": r["roll_number"],
                    "name": r["name"],
                    "marked_at": r["marked_at"]
                }
                for r in present
            ]
        }
    )


# ============================================================
# CLOSE SESSION
# ============================================================

@router.post("/api/faculty/sessions/{session_id}/close")
def close_session(request: Request, session_id: int):

    user = require_faculty(request)

    if not user:
        return JSONResponse(
            {"error": "Faculty login required."},
            status_code=401
        )

    conn = get_connection()

    session = conn.execute(
        """
        SELECT *
        FROM attendance_sessions
        WHERE id = ?
        AND faculty_user_id = ?
        """,
        (session_id, user["id"])
    ).fetchone()

    if not session:
        conn.close()

        return JSONResponse(
            {"error": "Session not found."},
            status_code=404
        )

    if session["is_active"] != 1:
        conn.close()

        return JSONResponse(
            {"error": "Session is already closed."},
            status_code=400
        )

    now = datetime.now()
    now_text = now.isoformat(timespec="seconds")

    students = conn.execute(
        """
        SELECT user_id
        FROM student_profiles
        WHERE division_id = ?
        """,
        (session["division_id"],)
    ).fetchall()

    absent_count = 0

    for student in students:

        existing = conn.execute(
            """
            SELECT id
            FROM attendance_records
            WHERE session_id = ?
            AND student_user_id = ?
            """,
            (
                session_id,
                student["user_id"]
            )
        ).fetchone()

        if not existing:

            conn.execute(
                """
                INSERT INTO attendance_records
                (
                    session_id,
                    student_user_id,
                    status,
                    method,
                    marked_at
                )
                VALUES (?, ?, 'absent', 'auto', ?)
                """,
                (
                    session_id,
                    student["user_id"],
                    now_text
                )
            )

            absent_count += 1

    conn.execute(
        """
        UPDATE attendance_sessions
        SET is_active = 0,
            closed_at = ?
        WHERE id = ?
        """,
        (
            now_text,
            session_id
        )
    )

    conn.commit()
    conn.close()

    return JSONResponse(
        {
            "success": True,
            "absent_count": absent_count
        }
    )


# ============================================================
# LEAVE REQUESTS (faculty review)
# ============================================================

LEAVE_PENDING = "Pending Leave"
LEAVE_APPROVED = "Approved Leave"
LEAVE_REJECTED = "Rejected Leave"


class LeaveDecision(BaseModel):
    # Accepts "Approved" / "Rejected" (any case); stored as the
    # full status names that the leave_requests table allows.
    status: str


@router.get("/faculty/leaves", response_class=HTMLResponse)
def faculty_leave_page(request: Request):

    user = require_faculty(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="faculty_leave.html",
        context={"current_user": user},
    )


@router.get("/api/faculty/leaves")
def get_faculty_leaves(request: Request):

    user = require_faculty(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Faculty login required."
        )

    db = get_connection()

    try:
        # Only leave for subjects/divisions assigned to this faculty.
        rows = db.execute(
            """
            SELECT
                lr.id,
                lr.session_id,
                lr.reason,
                lr.status,
                lr.submitted_at,
                lr.reviewed_at,
                sub.name AS subject_name,
                sub.code AS subject_code,
                s.started_at,
                sp.roll_number,
                u.name AS student_name,
                d.name AS division_name
            FROM leave_requests lr
            JOIN attendance_sessions s
                ON s.id = lr.session_id
            JOIN faculty_assignments fa
                ON fa.subject_id = s.subject_id
                AND fa.division_id = s.division_id
                AND fa.faculty_user_id = ?
            JOIN subjects sub
                ON sub.id = s.subject_id
            JOIN divisions d
                ON d.id = s.division_id
            JOIN student_profiles sp
                ON sp.user_id = lr.student_user_id
            JOIN users u
                ON u.id = lr.student_user_id
            ORDER BY
                CASE WHEN lr.status = 'Pending Leave' THEN 0 ELSE 1 END,
                lr.id DESC
            """,
            (user["id"],)
        ).fetchall()
    finally:
        db.close()

    return {
        "leaves": [dict(row) for row in rows]
    }


@router.post("/api/faculty/leaves/{leave_id}/decision")
def decide_leave(
    leave_id: int,
    data: LeaveDecision,
    request: Request
):

    user = require_faculty(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Faculty login required."
        )

    decision = data.status.strip().lower()

    if decision in ("approved", "approved leave"):
        new_status = LEAVE_APPROVED
    elif decision in ("rejected", "rejected leave"):
        new_status = LEAVE_REJECTED
    else:
        raise HTTPException(
            status_code=400,
            detail="Status must be Approved or Rejected."
        )

    db = get_connection()

    try:
        # The leave must belong to a class this faculty teaches.
        leave = db.execute(
            """
            SELECT lr.id, lr.status
            FROM leave_requests lr
            JOIN attendance_sessions s
                ON s.id = lr.session_id
            JOIN faculty_assignments fa
                ON fa.subject_id = s.subject_id
                AND fa.division_id = s.division_id
                AND fa.faculty_user_id = ?
            WHERE lr.id = ?
            """,
            (user["id"], leave_id)
        ).fetchone()

        if not leave:
            raise HTTPException(
                status_code=404,
                detail="Leave request not found."
            )

        if leave["status"] != LEAVE_PENDING:
            raise HTTPException(
                status_code=400,
                detail="This leave has already been reviewed."
            )

        db.execute(
            """
            UPDATE leave_requests
            SET
                status = ?,
                reviewed_at = ?,
                reviewed_by = ?
            WHERE id = ?
            AND status = 'Pending Leave'
            """,
            (
                new_status,
                datetime.now().isoformat(timespec="seconds"),
                user["id"],
                leave_id
            )
        )

        db.commit()
    finally:
        db.close()

    return {
        "success": True,
        "message": f"Leave {new_status.lower().replace(' leave', '')} successfully."
    }
