
from datetime import datetime, timedelta
import base64
import hashlib
import io
import secrets
import sqlite3

import qrcode
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from templating import templates
from pydantic import BaseModel

from auth import get_current_user
from database import get_connection


router = APIRouter(prefix="/faculty")

QR_VALIDITY_SECONDS = 30

DAY_NAMES = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}

LEAVE_PENDING = "Pending Leave"
LEAVE_APPROVED = "Approved Leave"
LEAVE_REJECTED = "Rejected Leave"


# ============================================================
# AUTHENTICATION
# ============================================================

def require_faculty(request: Request):
    """Return the active faculty account, otherwise None."""
    user = get_current_user(request)

    if not user or user.get("role") != "faculty":
        return None

    try:
        with get_connection() as conn:
            faculty = conn.execute(
                """
                SELECT id, name, email, employee_id, department_id
                FROM faculty_profiles
                WHERE id = ? AND is_active = 1
                """,
                (user["id"],),
            ).fetchone()

        if not faculty:
            request.session.clear()
            return None

        return {
            **user,
            "name": faculty["name"],
            "email": faculty["email"],
            "employee_id": faculty["employee_id"],
            "department_id": faculty["department_id"],
        }

    except (sqlite3.Error, KeyError, TypeError, ValueError):
        return None


def login_redirect():
    return RedirectResponse("/login", status_code=303)


def error_page(message: str, status_code: int = 400):
    return HTMLResponse(
        f"<h2>{message}</h2>",
        status_code=status_code,
    )


# ============================================================
# TIMETABLE HELPERS
# ============================================================

def parse_clock_time(value):
    """Accept HH:MM or HH:MM:SS database time values."""
    if not value:
        return None

    try:
        return datetime.strptime(value, "%H:%M:%S").time()
    except ValueError:
        try:
            return datetime.strptime(value, "%H:%M").time()
        except ValueError:
            return None


def get_today_timetable_entry(conn, timetable_id, faculty_id):
    """
    Verify that a timetable entry belongs to this faculty member,
    is a lecture/lab, is scheduled today, and is within its time window.
    """
    entry = conn.execute(
        """
        SELECT
            t.id,
            t.day_of_week,
            t.start_time,
            t.end_time,
            t.entry_type,
            t.title,
            t.subject_id,
            t.division_id,
            t.faculty_id,
            s.name AS subject_name,
            s.code AS subject_code,
            d.name AS division_name
        FROM timetable t
        JOIN subjects s ON s.id = t.subject_id
        JOIN divisions d ON d.id = t.division_id
        WHERE t.id = ?
          AND t.faculty_id = ?
          AND t.entry_type IN ('LECTURE', 'LAB')
        """,
        (timetable_id, faculty_id),
    ).fetchone()

    if not entry:
        return None, "Lecture not found or not assigned to you."

    now = datetime.now()

    if entry["day_of_week"] != now.weekday():
        return None, "This lecture is not scheduled for today."

    start = parse_clock_time(entry["start_time"])
    end = parse_clock_time(entry["end_time"])

    if not start or not end or start >= end:
        return None, "The timetable contains an invalid time."

    if now.time() < start:
        return None, f"Attendance cannot start before {start.strftime('%I:%M %p')}."

    if now.time() > end:
        return None, "This lecture has already ended."

    return entry, None


def validate_timetable_for_faculty(conn, timetable_id, faculty_id):
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
            t.faculty_id
        FROM timetable t
        WHERE t.id = ?
        """,
        (timetable_id,),
    ).fetchone()

    if not entry:
        raise HTTPException(404, "Timetable entry not found.")

    if entry["faculty_id"] != faculty_id:
        raise HTTPException(403, "This timetable entry is not assigned to you.")

    if entry["entry_type"] not in ("LECTURE", "LAB"):
        raise HTTPException(
            400,
            "Attendance cannot be started for this timetable entry.",
        )

    return entry


# ============================================================
# QR TOKEN HELPERS
# ============================================================

def create_qr_token(conn, session_id, now=None):
    """
    Create a short-lived QR token.

    Only the SHA-256 hash is stored in the database.
    The raw token is returned once to the authorized faculty client.
    """
    now = now or datetime.now()

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    expires_at = now + timedelta(seconds=QR_VALIDITY_SECONDS)

    conn.execute(
        """
        INSERT INTO qr_tokens
            (session_id, token_hash, valid_from, expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            session_id,
            token_hash,
            now.isoformat(timespec="seconds"),
            expires_at.isoformat(timespec="seconds"),
        ),
    )

    return {
        "raw_token": raw_token,
        "expires_at": expires_at.isoformat(timespec="seconds"),
    }


def validate_qr_token(conn, session_id: int, raw_token: str):
    """Return a valid token row, or None if it is invalid or expired."""
    if not raw_token:
        return None

    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = datetime.now().isoformat(timespec="seconds")

    return conn.execute(
        """
        SELECT id, session_id, valid_from, expires_at
        FROM qr_tokens
        WHERE session_id = ?
          AND token_hash = ?
          AND valid_from <= ?
          AND expires_at >= ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id, token_hash, now, now),
    ).fetchone()


# ============================================================
# CREATE ATTENDANCE SESSION
# ============================================================

def create_attendance_session(faculty, timetable_id, assignment_id=None):
    """
    Shared session-creation logic for both existing API routes.

    timetable_id is the primary input. assignment_id is optional
    for compatibility with the older frontend.
    """
    timetable_id = int(timetable_id)
    faculty_id = int(faculty["id"])

    conn = get_connection()

    try:
        now = datetime.now()
        lecture_date = now.strftime("%Y-%m-%d")

        # Verify that the timetable entry belongs to this faculty member.
        timetable = validate_timetable_for_faculty(
            conn,
            timetable_id,
            faculty_id,
        )

        # Confirm that the lecture is scheduled for today and is in progress.
        entry, error = get_today_timetable_entry(
            conn,
            timetable_id,
            faculty_id,
        )

        if error:
            raise HTTPException(status_code=400, detail=error)

        # Older clients may still send assignment_id.
        # New clients can start attendance directly from the timetable.
        if assignment_id is not None:
            assignment = conn.execute(
                """
                SELECT id, subject_id, division_id
                FROM faculty_assignments
                WHERE id = ? AND faculty_id = ?
                """,
                (int(assignment_id), faculty_id),
            ).fetchone()

            if not assignment:
                raise HTTPException(
                    status_code=403,
                    detail="You are not assigned to this class.",
                )

            if (
                assignment["subject_id"] != timetable["subject_id"]
                or assignment["division_id"] != timetable["division_id"]
            ):
                raise HTTPException(
                    status_code=403,
                    detail="The assignment does not match this timetable entry.",
                )

        # Prevent a second session for the same timetable entry and date.
        existing = conn.execute(
            """
            SELECT id, is_active
            FROM attendance_sessions
            WHERE timetable_id = ? AND lecture_date = ?
            """,
            (timetable_id, lecture_date),
        ).fetchone()

        if existing:
            if existing["is_active"] == 1:
                raise HTTPException(
                    status_code=409,
                    detail="Attendance is already active for this lecture.",
                )

            raise HTTPException(
                status_code=409,
                detail="Attendance has already been completed for this lecture.",
            )

        # Read the trusted college location configured by admin.
        college = conn.execute(
            """
            SELECT latitude, longitude, radius_meters
            FROM college_settings
            WHERE id = 1
            """
        ).fetchone()

        if not college:
            raise HTTPException(
                status_code=400,
                detail="The campus location has not been set up yet. Ask your administrator to set it under Campus.",
            )

        if (
            college["latitude"] is None
            or college["longitude"] is None
            or college["radius_meters"] is None
        ):
            raise HTTPException(
                status_code=400,
                detail="The college attendance location is incomplete.",
            )

        started_at = now.isoformat(timespec="seconds")

        cursor = conn.execute(
            """
            INSERT INTO attendance_sessions (
                faculty_id,
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
                faculty_id,
                timetable["subject_id"],
                timetable["division_id"],
                started_at,
                college["latitude"],
                college["longitude"],
                college["radius_meters"],
                timetable_id,
                lecture_date,
            ),
        )

        session_id = cursor.lastrowid

        qr = create_qr_token(conn, session_id, now)
        conn.commit()

        return {
            "success": True,
            "session_id": session_id,
            "timetable_id": timetable_id,
            "lecture_date": lecture_date,
            "started_at": started_at,
            "qr_token": qr["raw_token"],
            "qr_expires_at": qr["expires_at"],
            "seconds_left": QR_VALIDITY_SECONDS,
        }

    except HTTPException:
        conn.rollback()
        raise
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise HTTPException(
            status_code=409,
            detail="The attendance session could not be created. It may already exist.",
        ) from exc
    except sqlite3.Error as exc:
        conn.rollback()
        raise HTTPException(
            status_code=500,
            detail="A database error occurred while creating attendance.",
        ) from exc
    finally:
        conn.close()


class StartAttendanceRequest(BaseModel):
    timetable_id: int


@router.post("/api/attendance/start")
def start_attendance_session(
    request: Request,
    data: StartAttendanceRequest,
):
    faculty = require_faculty(request)

    if not faculty:
        raise HTTPException(401, "Faculty login required.")

    return create_attendance_session(
        faculty=faculty,
        timetable_id=data.timetable_id,
    )


@router.post("/api/faculty/sessions")
async def create_session(request: Request):
    """Compatibility endpoint for the older frontend."""
    faculty = require_faculty(request)

    if not faculty:
        return JSONResponse(
            {"error": "Faculty login required."},
            status_code=401,
        )

    try:
        data = await request.json()
        timetable_id = data.get("timetable_id")
        assignment_id = data.get("assignment_id")

        if timetable_id is None:
            return JSONResponse(
                {"error": "Timetable lecture is required."},
                status_code=400,
            )

        result = create_attendance_session(
            faculty=faculty,
            timetable_id=timetable_id,
            assignment_id=assignment_id,
        )

        return JSONResponse(result)

    except HTTPException as exc:
        return JSONResponse(
            {"error": exc.detail},
            status_code=exc.status_code,
        )
    except (ValueError, TypeError):
        return JSONResponse(
            {"error": "Invalid timetable or assignment ID."},
            status_code=400,
        )
    except Exception:
        return JSONResponse(
            {"error": "Invalid request data."},
            status_code=400,
        )


# ============================================================
# FACULTY DASHBOARD
# ============================================================

@router.get("/dashboard", response_class=HTMLResponse)
def faculty_dashboard(request: Request):
    faculty = require_faculty(request)

    if not faculty:
        return login_redirect()

    try:
        with get_connection() as conn:
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
                          AND sp.is_active = 1
                    ) AS student_count
                FROM faculty_assignments fa
                JOIN subjects s ON s.id = fa.subject_id
                JOIN divisions d ON d.id = fa.division_id
                JOIN semesters sem ON sem.id = d.semester_id
                JOIN departments dept ON dept.id = d.department_id
                WHERE fa.faculty_id = ?
                ORDER BY sem.number, d.name, s.name
                """,
                (faculty["id"],),
            ).fetchall()

            timetable = conn.execute(
                """
                SELECT
                    t.id,
                    t.day_of_week,
                    t.start_time,
                    t.end_time,
                    t.entry_type,
                    t.title,
                    s.name AS subject_name,
                    s.code AS subject_code,
                    d.name AS division_name,
                    sem.number AS semester_number
                FROM timetable t
                LEFT JOIN subjects s ON s.id = t.subject_id
                LEFT JOIN divisions d ON d.id = t.division_id
                LEFT JOIN semesters sem ON sem.id = d.semester_id
                WHERE t.faculty_id = ?
                ORDER BY t.day_of_week, t.start_time
                """,
                (faculty["id"],),
            ).fetchall()

            today_sessions = conn.execute(
                """
                SELECT
                    ats.id,
                    ats.timetable_id,
                    ats.lecture_date,
                    ats.started_at,
                    ats.closed_at,
                    ats.is_active,
                    s.name AS subject_name,
                    d.name AS division_name
                FROM attendance_sessions ats
                LEFT JOIN subjects s ON s.id = ats.subject_id
                LEFT JOIN divisions d ON d.id = ats.division_id
                WHERE ats.faculty_id = ?
                  AND ats.lecture_date = ?
                ORDER BY ats.started_at DESC
                """,
                (faculty["id"], datetime.now().strftime("%Y-%m-%d")),
            ).fetchall()

            faculty_record = conn.execute(
                """
                SELECT fp.*, d.name AS department_name, d.code AS department_code
                FROM faculty_profiles fp
                LEFT JOIN departments d ON d.id = fp.department_id
                WHERE fp.id = ?
                """,
                (faculty["id"],),
            ).fetchone()

        return templates.TemplateResponse(
            "faculty_dashboard.html",
            {
                "request": request,
                "user": faculty,
                "faculty": faculty_record,
                "assignments": assignments,
                "timetable": timetable,
                "today_sessions": today_sessions,
            },
        )

    except sqlite3.Error:
        return error_page("Unable to load the faculty dashboard.", 500)


# ============================================================
# FACULTY ASSIGNMENT / CLASS
# ============================================================

@router.get("/assignments/{assignment_id}", response_class=HTMLResponse)
def faculty_assignment(request: Request, assignment_id: int):
    faculty = require_faculty(request)

    if not faculty:
        return login_redirect()

    try:
        with get_connection() as conn:
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
                JOIN subjects s ON s.id = fa.subject_id
                JOIN divisions d ON d.id = fa.division_id
                JOIN semesters sem ON sem.id = d.semester_id
                JOIN departments dept ON dept.id = d.department_id
                WHERE fa.id = ? AND fa.faculty_id = ?
                """,
                (assignment_id, faculty["id"]),
            ).fetchone()

            if not assignment:
                return error_page("Assignment not found or not assigned to you.", 404)

            students = conn.execute(
                """
                SELECT id, roll_number, name, email
                FROM student_profiles
                WHERE division_id = ? AND is_active = 1
                ORDER BY roll_number, name
                """,
                (assignment["division_id"],),
            ).fetchall()

        return templates.TemplateResponse(
            "faculty_assignment.html",
            {
                "request": request,
                "user": faculty,
                "assignment": assignment,
                "students": students,
            },
        )

    except sqlite3.Error:
        return error_page("Unable to load the class.", 500)


# ============================================================
# START ATTENDANCE PAGE
# ============================================================

@router.get(
    "/assignments/{assignment_id}/start",
    response_class=HTMLResponse,
)
def start_attendance_page(request: Request, assignment_id: int):
    faculty = require_faculty(request)

    if not faculty:
        return login_redirect()

    try:
        with get_connection() as conn:
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
                JOIN subjects s ON s.id = fa.subject_id
                JOIN divisions d ON d.id = fa.division_id
                JOIN semesters sem ON sem.id = d.semester_id
                WHERE fa.id = ? AND fa.faculty_id = ?
                """,
                (assignment_id, faculty["id"]),
            ).fetchone()

        if not assignment:
            return error_page("Assignment not found.", 404)

        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        lectures = []

        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT t.id, t.start_time, t.end_time, t.entry_type,
                       (SELECT id FROM attendance_sessions x
                         WHERE x.timetable_id = t.id AND x.lecture_date = ?) AS session_id,
                       (SELECT is_active FROM attendance_sessions x
                         WHERE x.timetable_id = t.id AND x.lecture_date = ?) AS session_active
                FROM timetable t
                WHERE t.faculty_id = ?
                  AND t.subject_id = ?
                  AND t.division_id = ?
                  AND t.day_of_week = ?
                  AND t.entry_type IN ('LECTURE', 'LAB')
                ORDER BY t.start_time
                """,
                (
                    today, today, faculty["id"],
                    assignment["subject_id"], assignment["division_id"],
                    now.weekday(),
                ),
            ).fetchall()

        for row in rows:
            start = parse_clock_time(row["start_time"])
            end = parse_clock_time(row["end_time"])
            if row["session_id"] and row["session_active"] == 1:
                state = "active"
            elif row["session_id"]:
                state = "done"
            elif start and end and now.time() < start:
                state = "upcoming"
            elif start and end and now.time() > end:
                state = "ended"
            else:
                state = "open"
            lectures.append(
                {
                    "id": row["id"],
                    "start": start.strftime("%I:%M %p").lstrip("0") if start else row["start_time"],
                    "end": end.strftime("%I:%M %p").lstrip("0") if end else row["end_time"],
                    "type": row["entry_type"].title(),
                    "state": state,
                    "session_id": row["session_id"],
                }
            )

        return templates.TemplateResponse(
            request=request,
            name="faculty_start_session.html",
            context={
                "user": faculty,
                "assignment": assignment,
                "lectures": lectures,
            },
        )

    except sqlite3.Error:
        return error_page("Unable to load the attendance page.", 500)


# ============================================================
# FACULTY TIMETABLE PAGE
# ============================================================

@router.get("/timetable", response_class=HTMLResponse)
def faculty_timetable(request: Request):
    faculty = require_faculty(request)

    if not faculty:
        return login_redirect()

    try:
        with get_connection() as conn:
            timetable = conn.execute(
                """
                SELECT
                    t.id,
                    t.day_of_week,
                    t.start_time,
                    t.end_time,
                    t.entry_type,
                    t.title,
                    s.name AS subject_name,
                    s.code AS subject_code,
                    d.name AS division_name,
                    sem.number AS semester_number,
                    dept.code AS department_code,
                    fp.name AS faculty_name
                FROM timetable t
                LEFT JOIN subjects s ON s.id = t.subject_id
                LEFT JOIN divisions d ON d.id = t.division_id
                LEFT JOIN semesters sem ON sem.id = d.semester_id
                LEFT JOIN departments dept ON dept.id = d.department_id
                LEFT JOIN faculty_profiles fp ON fp.id = t.faculty_id
                WHERE t.faculty_id = ?
                   OR t.entry_type IN ('HOD_USE', 'OTHER')
                ORDER BY t.day_of_week, t.start_time
                """,
                (faculty["id"],),
            ).fetchall()

        return templates.TemplateResponse(
            "faculty_timetable.html",
            {
                "request": request,
                "user": faculty,
                "current_user": faculty,
                "timetable": timetable,
                "day_names": DAY_NAMES,
            },
        )

    except sqlite3.Error:
        return error_page("Unable to load the timetable.", 500)


@router.get("/api/timetable")
def get_faculty_timetable(request: Request):
    faculty = require_faculty(request)

    if not faculty:
        raise HTTPException(401, "Faculty login required.")

    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    t.id,
                    t.day_of_week,
                    t.start_time,
                    t.end_time,
                    t.entry_type,
                    t.title,
                    s.name AS subject_name,
                    s.code AS subject_code,
                    d.name AS division_name
                FROM timetable t
                LEFT JOIN subjects s ON s.id = t.subject_id
                LEFT JOIN divisions d ON d.id = t.division_id
                WHERE t.faculty_id = ?
                ORDER BY t.day_of_week, t.start_time
                """,
                (faculty["id"],),
            ).fetchall()

        timetable = [
            {
                "id": row["id"],
                "day_of_week": row["day_of_week"],
                "day": DAY_NAMES.get(row["day_of_week"], "Unknown"),
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "entry_type": row["entry_type"],
                "title": row["title"],
                "subject_name": row["subject_name"],
                "subject_code": row["subject_code"],
                "division_name": row["division_name"],
            }
            for row in rows
        ]

        return {
            "faculty_id": faculty["id"],
            "timetable": timetable,
        }

    except sqlite3.Error:
        raise HTTPException(500, "Unable to load the timetable.")


# ============================================================
# LIVE ATTENDANCE PAGE
# ============================================================

@router.get("/sessions/{session_id}/live", response_class=HTMLResponse)
def live_session_page(request: Request, session_id: int):
    faculty = require_faculty(request)

    if not faculty:
        return login_redirect()

    try:
        with get_connection() as conn:
            session = conn.execute(
                """
                SELECT
                    a.id,
                    a.is_active,
                    a.started_at,
                    a.closed_at,
                    a.subject_id,
                    a.division_id,
                    a.lecture_date,
                    s.name AS subject_name,
                    s.code AS subject_code,
                    d.name AS division_name,
                    sem.number AS semester_number
                FROM attendance_sessions a
                JOIN subjects s ON s.id = a.subject_id
                JOIN divisions d ON d.id = a.division_id
                JOIN semesters sem ON sem.id = d.semester_id
                WHERE a.id = ? AND a.faculty_id = ?
                """,
                (session_id, faculty["id"]),
            ).fetchone()

        if not session:
            return error_page("Attendance session not found.", 404)

        return templates.TemplateResponse(
            "faculty_session_live.html",
            {
                "request": request,
                "user": faculty,
                "session": session,
            },
        )

    except sqlite3.Error:
        return error_page("Unable to load the attendance session.", 500)


# ============================================================
# GET QR IMAGE AND PRESENT STUDENTS
# ============================================================

@router.get("/api/faculty/sessions/{session_id}/qr")
def get_qr(request: Request, session_id: int):
    faculty = require_faculty(request)

    if not faculty:
        return JSONResponse(
            {"error": "Faculty login required."},
            status_code=401,
        )

    conn = get_connection()

    try:
        session = conn.execute(
            """
            SELECT id, is_active
            FROM attendance_sessions
            WHERE id = ? AND faculty_id = ?
            """,
            (session_id, faculty["id"]),
        ).fetchone()

        if not session:
            return JSONResponse(
                {"error": "Session not found."},
                status_code=404,
            )

        if session["is_active"] != 1:
            return JSONResponse(
                {"error": "Session is closed."},
                status_code=400,
            )

        now = datetime.now()

        # Remove expired tokens for this session before adding another.
        conn.execute(
            """
            DELETE FROM qr_tokens
            WHERE session_id = ? AND expires_at < ?
            """,
            (session_id, now.isoformat(timespec="seconds")),
        )

        # Every QR refresh generates a fresh, short-lived token.
        qr_data = create_qr_token(conn, session_id, now)

        qr = qrcode.QRCode(version=1, box_size=8, border=4)
        qr.add_data(qr_data["raw_token"])
        qr.make(fit=True)

        image = qr.make_image()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")

        qr_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        present = conn.execute(
            """
            SELECT
                ar.student_id,
                sp.roll_number,
                sp.name,
                ar.marked_at
            FROM attendance_records ar
            JOIN student_profiles sp ON sp.id = ar.student_id
            WHERE ar.session_id = ?
              AND ar.status = 'present'
            ORDER BY sp.roll_number
            """,
            (session_id,),
        ).fetchall()

        conn.commit()

        return JSONResponse(
            {
                "token": qr_data["raw_token"],
                "seconds_left": QR_VALIDITY_SECONDS,
                "expires_at": qr_data["expires_at"],
                "qr_image": qr_base64,
                "present_count": len(present),
                "present_students": [
                    {
                        "roll_number": row["roll_number"],
                        "name": row["name"],
                        "marked_at": row["marked_at"],
                    }
                    for row in present
                ],
            }
        )

    except sqlite3.Error:
        conn.rollback()
        return JSONResponse(
            {"error": "Unable to generate the QR code."},
            status_code=500,
        )
    finally:
        conn.close()


# ============================================================
# LIVE ATTENDANCE LIST
# ============================================================

@router.get("/api/faculty/sessions/{session_id}/attendance")
def live_attendance(request: Request, session_id: int):
    faculty = require_faculty(request)

    if not faculty:
        return JSONResponse(
            {"error": "Faculty login required."},
            status_code=401,
        )

    try:
        with get_connection() as conn:
            session = conn.execute(
                """
                SELECT id, division_id, is_active
                FROM attendance_sessions
                WHERE id = ? AND faculty_id = ?
                """,
                (session_id, faculty["id"]),
            ).fetchone()

            if not session:
                return JSONResponse(
                    {"error": "Session not found."},
                    status_code=404,
                )

            present = conn.execute(
                """
                SELECT sp.roll_number, sp.name, ar.marked_at
                FROM attendance_records ar
                JOIN student_profiles sp ON sp.id = ar.student_id
                WHERE ar.session_id = ? AND ar.status = 'present'
                ORDER BY sp.roll_number
                """,
                (session_id,),
            ).fetchall()

            total = conn.execute(
                """
                SELECT COUNT(*)
                FROM student_profiles
                WHERE division_id = ? AND is_active = 1
                """,
                (session["division_id"],),
            ).fetchone()[0]

        return JSONResponse(
            {
                "is_active": session["is_active"] == 1,
                "present_count": len(present),
                "total_students": total,
                "present_students": [
                    {
                        "roll_number": row["roll_number"],
                        "name": row["name"],
                        "marked_at": row["marked_at"],
                    }
                    for row in present
                ],
            }
        )

    except sqlite3.Error:
        return JSONResponse(
            {"error": "Unable to load attendance records."},
            status_code=500,
        )


# ============================================================
# CLOSE ATTENDANCE SESSION
# ============================================================

@router.post("/api/faculty/sessions/{session_id}/close")
def close_session(request: Request, session_id: int):
    faculty = require_faculty(request)

    if not faculty:
        return JSONResponse(
            {"error": "Faculty login required."},
            status_code=401,
        )

    conn = get_connection()

    try:
        session = conn.execute(
            """
            SELECT id, division_id, is_active
            FROM attendance_sessions
            WHERE id = ? AND faculty_id = ?
            """,
            (session_id, faculty["id"]),
        ).fetchone()

        if not session:
            return JSONResponse(
                {"error": "Session not found."},
                status_code=404,
            )

        if session["is_active"] != 1:
            return JSONResponse(
                {"error": "Session is already closed."},
                status_code=400,
            )

        now_text = datetime.now().isoformat(timespec="seconds")

        # Insert absent records only for students without a record.
        conn.execute(
            """
            INSERT INTO attendance_records (
                session_id,
                student_id,
                status,
                method,
                marked_at
            )
            SELECT ?, sp.id, 'absent', 'auto', ?
            FROM student_profiles sp
            WHERE sp.division_id = ?
              AND sp.is_active = 1
              AND NOT EXISTS (
                  SELECT 1
                  FROM attendance_records ar
                  WHERE ar.session_id = ?
                    AND ar.student_id = sp.id
              )
            """,
            (
                session_id,
                now_text,
                session["division_id"],
                session_id,
            ),
        )

        absent_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM attendance_records
            WHERE session_id = ?
              AND status = 'absent'
              AND method = 'auto'
            """,
            (session_id,),
        ).fetchone()[0]

        conn.execute(
            """
            UPDATE attendance_sessions
            SET is_active = 0, closed_at = ?
            WHERE id = ? AND faculty_id = ?
            """,
            (now_text, session_id, faculty["id"]),
        )

        # Invalidate outstanding QR tokens when attendance is closed.
        conn.execute(
            "DELETE FROM qr_tokens WHERE session_id = ?",
            (session_id,),
        )

        conn.commit()

        return JSONResponse(
            {
                "success": True,
                "absent_count": absent_count,
            }
        )

    except sqlite3.Error:
        conn.rollback()
        return JSONResponse(
            {"error": "Unable to close the attendance session."},
            status_code=500,
        )
    finally:
        conn.close()


# ============================================================
# LEAVE REQUESTS
# ============================================================

class LeaveDecision(BaseModel):
    status: str


@router.get("/leaves", response_class=HTMLResponse)
def faculty_leave_page(request: Request):
    faculty = require_faculty(request)

    if not faculty:
        return login_redirect()

    return templates.TemplateResponse(
        "faculty_leave.html",
        {
            "request": request,
            "user": faculty,
            "current_user": faculty,
        },
    )


@router.get("/api/faculty/leaves")
def get_faculty_leaves(request: Request):
    faculty = require_faculty(request)

    if not faculty:
        raise HTTPException(401, "Faculty login required.")

    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    lr.id,
                    lr.student_id,
                    lr.session_id,
                    lr.timetable_id,
                    lr.lecture_date,
                    lr.reason,
                    lr.status,
                    lr.submitted_at,
                    lr.reviewed_at,
                    s.name AS subject_name,
                    s.code AS subject_code,
                    t.start_time,
                    t.end_time,
                    sp.roll_number,
                    sp.name AS student_name,
                    d.name AS division_name
                FROM leave_requests lr
                JOIN timetable t ON t.id = lr.timetable_id
                JOIN subjects s ON s.id = t.subject_id
                JOIN divisions d ON d.id = t.division_id
                JOIN student_profiles sp ON sp.id = lr.student_id
                WHERE t.faculty_id = ?
                ORDER BY
                    CASE WHEN lr.status = 'Pending Leave' THEN 0 ELSE 1 END,
                    lr.lecture_date DESC,
                    lr.id DESC
                """,
                (faculty["id"],),
            ).fetchall()

        return {"leaves": [dict(row) for row in rows]}

    except sqlite3.Error:
        raise HTTPException(500, "Unable to load leave requests.")


@router.post("/api/faculty/leaves/{leave_id}/decision")
def decide_leave(
    leave_id: int,
    data: LeaveDecision,
    request: Request,
):
    faculty = require_faculty(request)

    if not faculty:
        raise HTTPException(401, "Faculty login required.")

    decision = data.status.strip().lower()

    if decision in {"approved", "approved leave"}:
        new_status = LEAVE_APPROVED
    elif decision in {"rejected", "rejected leave"}:
        new_status = LEAVE_REJECTED
    else:
        raise HTTPException(
            400,
            "Status must be Approved or Rejected.",
        )

    conn = get_connection()

    try:
        leave = conn.execute(
            """
            SELECT lr.id, lr.status
            FROM leave_requests lr
            JOIN timetable t ON t.id = lr.timetable_id
            WHERE lr.id = ?
              AND t.faculty_id = ?
            """,
            (leave_id, faculty["id"]),
        ).fetchone()

        if not leave:
            raise HTTPException(404, "Leave request not found.")

        if leave["status"] != LEAVE_PENDING:
            raise HTTPException(
                400,
                "This leave request has already been reviewed.",
            )

        reviewed_at = datetime.now().isoformat(timespec="seconds")

        cursor = conn.execute(
            """
            UPDATE leave_requests
            SET status = ?, reviewed_at = ?, reviewed_by = ?
            WHERE id = ? AND status = ?
            """,
            (
                new_status,
                reviewed_at,
                faculty["id"],
                leave_id,
                LEAVE_PENDING,
            ),
        )

        if cursor.rowcount != 1:
            conn.rollback()
            raise HTTPException(
                409,
                "The leave request has already been updated.",
            )

        conn.commit()

        return {
            "success": True,
            "message": (
                "Leave approved successfully."
                if new_status == LEAVE_APPROVED
                else "Leave rejected successfully."
            ),
        }

    except HTTPException:
        conn.rollback()
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        raise HTTPException(
            500,
            "Unable to update the leave request.",
        ) from exc
    finally:
        conn.close()