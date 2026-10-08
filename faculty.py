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


router = APIRouter(prefix="/faculty")
templates = Jinja2Templates(directory="templates")

QR_VALIDITY_SECONDS = 30


# ============================================================
# FACULTY AUTH
# ============================================================

def require_faculty(request: Request):
    """
    Return the logged-in faculty account.
    Otherwise return None.
    """

    user = get_current_user(request)

    if not user:
        return None

    if user["role"] != "faculty":
        return None

    return user


# ============================================================
# GET TODAY'S TIMETABLE ENTRY
# ============================================================

def get_today_timetable_entry(
    conn,
    timetable_id,
    faculty_id,
):
    """
    Verify that the timetable entry belongs to this faculty,
    is scheduled for today, and is a lecture/lab.
    """

    now = datetime.now()

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
            t.faculty_id,

            s.name AS subject_name,
            s.code AS subject_code,

            d.name AS division_name

        FROM timetable t

        JOIN subjects s
            ON s.id = t.subject_id

        JOIN divisions d
            ON d.id = t.division_id

        WHERE t.id = ?
          AND t.faculty_id = ?
          AND t.entry_type IN ('LECTURE', 'LAB')
        """,
        (
            timetable_id,
            faculty_id,
        ),
    ).fetchone()

    if not entry:
        return None, "Timetable lecture not found."

    if entry["day_of_week"] != now.weekday():
        return None, "This lecture is not scheduled for today."

    # ------------------------------------------------------------
    # Check current time against scheduled lecture time
    # ------------------------------------------------------------

    try:
        current_time = now.strftime("%H:%M")

        if current_time < entry["start_time"]:
            return (
                None,
                f"Attendance cannot be started before "
                f"{entry['start_time']}.",
            )

        if current_time > entry["end_time"]:
            return (
                None,
                "This lecture has already ended.",
            )

    except Exception:
        return None, "Invalid timetable time."

    return entry, None

# ============================================================
# FACULTY DASHBOARD
# ============================================================

@router.get(
    "/faculty/dashboard",
    response_class=HTMLResponse,
)
def faculty_dashboard(request: Request):

    user = require_faculty(request)

    if not user:
        return RedirectResponse(
            "/login",
            status_code=303,
        )

    conn = get_connection()

    try:

        faculty = conn.execute(
            """
            SELECT
                fp.id,
                fp.name AS faculty_name,
                fp.email,
                fp.employee_id,
                fp.department_id,

                d.name AS department_name,
                d.code AS department_code

            FROM faculty_profiles fp

            JOIN departments d
                ON d.id = fp.department_id

            WHERE fp.id = ?
              AND fp.is_active = 1
            """,
            (user["id"],),
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

            WHERE fa.faculty_id = ?

            ORDER BY
                sem.number,
                d.name,
                s.name
            """,
            (user["id"],),
        ).fetchall()

    finally:
        conn.close()

    return templates.TemplateResponse(
        "faculty_dashboard.html",
        {
            "request": request,
            "user": user,
            "faculty": faculty,
            "assignments": assignments,
        },
    )


# ============================================================
# FACULTY ASSIGNMENT / CLASS
# ============================================================

@router.get(
    "/faculty/assignments/{assignment_id}",
    response_class=HTMLResponse,
)
def faculty_assignment(
    request: Request,
    assignment_id: int,
):

    user = require_faculty(request)

    if not user:
        return RedirectResponse(
            "/login",
            status_code=303,
        )

    conn = get_connection()

    try:

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
              AND fa.faculty_id = ?
            """,
            (
                assignment_id,
                user["id"],
            ),
        ).fetchone()

        if not assignment:
            return HTMLResponse(
                "<h2>Assignment not found or not assigned to you.</h2>",
                status_code=404,
            )

        students = conn.execute(
            """
            SELECT
                sp.id,
                sp.roll_number,
                sp.name,
                sp.email

            FROM student_profiles sp

            WHERE sp.division_id = ?

            ORDER BY sp.roll_number
            """,
            (assignment["division_id"],),
        ).fetchall()

    finally:
        conn.close()

    return templates.TemplateResponse(
        "faculty_assignment.html",
        {
            "request": request,
            "user": user,
            "assignment": assignment,
            "students": students,
        },
    )


# ============================================================
# START ATTENDANCE PAGE
# ============================================================

@router.get(
    "/faculty/assignments/{assignment_id}/start",
    response_class=HTMLResponse,
)
def start_attendance_page(
    request: Request,
    assignment_id: int,
):

    user = require_faculty(request)

    if not user:
        return RedirectResponse(
            "/login",
            status_code=303,
        )

    conn = get_connection()

    try:

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
              AND fa.faculty_id = ?
            """,
            (
                assignment_id,
                user["id"],
            ),
        ).fetchone()

    finally:
        conn.close()

    if not assignment:
        return HTMLResponse(
            "<h2>Assignment not found.</h2>",
            status_code=404,
        )

    return templates.TemplateResponse(
        "faculty_start_session.html",
        {
            "request": request,
            "user": user,
            "assignment": assignment,
        },
    )


# ============================================================
# FACULTY TIMETABLE
# ============================================================

@router.get(
    "/faculty/timetable",
    response_class=HTMLResponse,
)
def faculty_timetable(request: Request):

    faculty = require_faculty(request)

    if not faculty:
        return RedirectResponse(
            "/login",
            status_code=303,
        )

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

                departments.code AS department_code,

                faculty_profiles.name AS faculty_name

            FROM timetable

            LEFT JOIN subjects
                ON subjects.id = timetable.subject_id

            LEFT JOIN divisions
                ON divisions.id = timetable.division_id

            LEFT JOIN semesters
                ON semesters.id = divisions.semester_id

            LEFT JOIN departments
                ON departments.id = divisions.department_id

            LEFT JOIN faculty_profiles
                ON faculty_profiles.id = timetable.faculty_id

            WHERE timetable.faculty_id = ?
               OR timetable.entry_type IN ('HOD_USE', 'OTHER')

            ORDER BY
                timetable.day_of_week,
                timetable.start_time
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
            status_code=401,
        )

    try:
        data = await request.json()

    except Exception:
        return JSONResponse(
            {"error": "Invalid request data."},
            status_code=400,
        )

    assignment_id = data.get("assignment_id")
    timetable_id = data.get("timetable_id")

    if assignment_id is None:
        return JSONResponse(
            {"error": "Assignment is required."},
            status_code=400,
        )

    if timetable_id is None:
        return JSONResponse(
            {"error": "Timetable lecture is required."},
            status_code=400,
        )

    try:
        assignment_id = int(assignment_id)
        timetable_id = int(timetable_id)

    except (TypeError, ValueError):
        return JSONResponse(
            {"error": "Invalid assignment or timetable."},
            status_code=400,
        )

    conn = get_connection()

    try:

        # --------------------------------------------------------
        # College trusted location
        # --------------------------------------------------------

        college_location = conn.execute(
            """
            SELECT
                latitude,
                longitude,
                radius_meters
            FROM college_settings
            WHERE id = 1
            """
        ).fetchone()

        if not college_location:
            return JSONResponse(
                {
                    "error": (
                        "College attendance location has not "
                        "been configured by Admin."
                    )
                },
                status_code=400,
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
              AND faculty_id = ?
            """,
            (
                assignment_id,
                user["id"],
            ),
        ).fetchone()

        if not assignment:
            return JSONResponse(
                {
                    "error": "You are not assigned to this class."
                },
                status_code=403,
            )

        # --------------------------------------------------------
        # Verify today's timetable entry
        # --------------------------------------------------------

        timetable, error = get_today_timetable_entry(
            conn,
            timetable_id,
            user["id"],
        )

        if error:
            return JSONResponse(
                {"error": error},
                status_code=400,
            )

        # --------------------------------------------------------
        # Match timetable with assignment
        # --------------------------------------------------------

        if (
            timetable["subject_id"] != assignment["subject_id"]
            or timetable["division_id"] != assignment["division_id"]
            or timetable["faculty_id"] != user["id"]
        ):
            return JSONResponse(
                {
                    "error": (
                        "This timetable lecture is not "
                        "assigned to you."
                    )
                },
                status_code=403,
            )

        # --------------------------------------------------------
        # Server determines today's lecture date
        # --------------------------------------------------------

        today = datetime.now()
        lecture_date = today.strftime("%Y-%m-%d")

        # --------------------------------------------------------
        # Prevent duplicate attendance session
        # --------------------------------------------------------

        existing = conn.execute(
            """
            SELECT
                id,
                is_active

            FROM attendance_sessions

            WHERE timetable_id = ?
              AND lecture_date = ?
            """,
            (
                timetable_id,
                lecture_date,
            ),
        ).fetchone()

        if existing:

            if existing["is_active"] == 1:
                return JSONResponse(
                    {
                        "error": (
                            "Attendance is already active "
                            "for this lecture."
                        ),
                        "session_id": existing["id"],
                    },
                    status_code=409,
                )

            return JSONResponse(
                {
                    "error": (
                        "Attendance has already been "
                        "completed for this lecture."
                    ),
                    "session_id": existing["id"],
                },
                status_code=409,
            )

        # --------------------------------------------------------
        # Create attendance session
        # --------------------------------------------------------

        now = datetime.now()

        now_text = now.isoformat(
            timespec="seconds"
        )

        cursor = conn.execute(
            """
            INSERT INTO attendance_sessions
            (
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
                user["id"],
                assignment["subject_id"],
                assignment["division_id"],
                now_text,
                college_location["latitude"],
                college_location["longitude"],
                college_location["radius_meters"],
                timetable_id,
                lecture_date,
            ),
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
                expires.isoformat(
                    timespec="seconds"
                ),
            ),
        )

        conn.commit()

    finally:
        conn.close()

    return JSONResponse(
        {
            "success": True,
            "session_id": session_id,
            "timetable_id": timetable_id,
            "lecture_date": lecture_date,
        }
    )


# ============================================================
# LIVE ATTENDANCE PAGE
# ============================================================

@router.get(
    "/faculty/sessions/{session_id}/live",
    response_class=HTMLResponse,
)
def live_session_page(
    request: Request,
    session_id: int,
):

    user = require_faculty(request)

    if not user:
        return RedirectResponse(
            "/login",
            status_code=303,
        )

    conn = get_connection()

    try:

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
              AND a.faculty_id = ?
            """,
            (
                session_id,
                user["id"],
            ),
        ).fetchone()

    finally:
        conn.close()

    if not session:
        return HTMLResponse(
            "<h2>Attendance session not found.</h2>",
            status_code=404,
        )

    return templates.TemplateResponse(
        "faculty_session_live.html",
        {
            "request": request,
            "user": user,
            "session": session,
        },
    )


# ============================================================
# GET CURRENT QR
# ============================================================

@router.get(
    "/api/faculty/sessions/{session_id}/qr"
)
def get_qr(
    request: Request,
    session_id: int,
):

    user = require_faculty(request)

    if not user:
        return JSONResponse(
            {"error": "Faculty login required."},
            status_code=401,
        )

    conn = get_connection()

    try:

        session = conn.execute(
            """
            SELECT *
            FROM attendance_sessions

            WHERE id = ?
              AND faculty_id = ?
            """,
            (
                session_id,
                user["id"],
            ),
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
                now.isoformat(
                    timespec="seconds"
                ),
                expires.isoformat(
                    timespec="seconds"
                ),
            ),
        )

        conn.commit()

        # --------------------------------------------------------
        # Generate QR image
        # --------------------------------------------------------

        qr = qrcode.QRCode(
            version=1,
            box_size=8,
            border=4,
        )

        qr.add_data(token)
        qr.make(fit=True)

        image = qr.make_image()

        buffer = io.BytesIO()

        image.save(
            buffer,
            format="PNG",
        )

        qr_base64 = base64.b64encode(
            buffer.getvalue()
        ).decode("utf-8")

        # --------------------------------------------------------
        # Present students
        # --------------------------------------------------------

        present = conn.execute(
            """
            SELECT
                ar.student_id,
                sp.roll_number,
                sp.name,
                ar.marked_at

            FROM attendance_records ar

            JOIN student_profiles sp
                ON sp.id = ar.student_id

            WHERE ar.session_id = ?
              AND ar.status = 'present'

            ORDER BY sp.roll_number
            """,
            (session_id,),
        ).fetchall()

    finally:
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
                    "marked_at": row["marked_at"],
                }
                for row in present
            ],
        }
    )


# ============================================================
# LIVE ATTENDANCE LIST
# ============================================================

@router.get(
    "/api/faculty/sessions/{session_id}/attendance"
)
def live_attendance(
    request: Request,
    session_id: int,
):

    user = require_faculty(request)

    if not user:
        return JSONResponse(
            {"error": "Faculty login required."},
            status_code=401,
        )

    conn = get_connection()

    try:

        session = conn.execute(
            """
            SELECT
                id,
                division_id,
                is_active

            FROM attendance_sessions

            WHERE id = ?
              AND faculty_id = ?
            """,
            (
                session_id,
                user["id"],
            ),
        ).fetchone()

        if not session:
            return JSONResponse(
                {"error": "Session not found."},
                status_code=404,
            )

        present = conn.execute(
            """
            SELECT
                sp.roll_number,
                sp.name,
                ar.marked_at

            FROM attendance_records ar

            JOIN student_profiles sp
                ON sp.id = ar.student_id

            WHERE ar.session_id = ?
              AND ar.status = 'present'

            ORDER BY sp.roll_number
            """,
            (session_id,),
        ).fetchall()

        total = conn.execute(
            """
            SELECT COUNT(*)
            FROM student_profiles
            WHERE division_id = ?
            """,
            (session["division_id"],),
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
                    "roll_number": row["roll_number"],
                    "name": row["name"],
                    "marked_at": row["marked_at"],
                }
                for row in present
            ],
        }
    )


# ============================================================
# CLOSE SESSION
# ============================================================

@router.post(
    "/api/faculty/sessions/{session_id}/close"
)
def close_session(
    request: Request,
    session_id: int,
):

    user = require_faculty(request)

    if not user:
        return JSONResponse(
            {"error": "Faculty login required."},
            status_code=401,
        )

    conn = get_connection()

    try:

        session = conn.execute(
            """
            SELECT *
            FROM attendance_sessions

            WHERE id = ?
              AND faculty_id = ?
            """,
            (
                session_id,
                user["id"],
            ),
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

        now = datetime.now()

        now_text = now.isoformat(
            timespec="seconds"
        )

        students = conn.execute(
            """
            SELECT id
            FROM student_profiles
            WHERE division_id = ?
            """,
            (session["division_id"],),
        ).fetchall()

        absent_count = 0

        for student in students:

            existing = conn.execute(
                """
                SELECT id
                FROM attendance_records

                WHERE session_id = ?
                  AND student_id = ?
                """,
                (
                    session_id,
                    student["id"],
                ),
            ).fetchone()

            if not existing:

                conn.execute(
                    """
                    INSERT INTO attendance_records
                    (
                        session_id,
                        student_id,
                        status,
                        method,
                        marked_at
                    )

                    VALUES (
                        ?,
                        ?,
                        'absent',
                        'auto',
                        ?
                    )
                    """,
                    (
                        session_id,
                        student["id"],
                        now_text,
                    ),
                )

                absent_count += 1

        conn.execute(
            """
            UPDATE attendance_sessions

            SET
                is_active = 0,
                closed_at = ?

            WHERE id = ?
            """,
            (
                now_text,
                session_id,
            ),
        )

        conn.commit()

    finally:
        conn.close()

    return JSONResponse(
        {
            "success": True,
            "absent_count": absent_count,
        }
    )


# ============================================================
# LEAVE REQUESTS
# ============================================================

LEAVE_PENDING = "Pending Leave"
LEAVE_APPROVED = "Approved Leave"
LEAVE_REJECTED = "Rejected Leave"


class LeaveDecision(BaseModel):
    status: str


# ------------------------------------------------------------
# Faculty Leave Page
# ------------------------------------------------------------

@router.get(
    "/faculty/leaves",
    response_class=HTMLResponse,
)
def faculty_leave_page(request: Request):

    user = require_faculty(request)

    if not user:
        return RedirectResponse(
            "/login",
            status_code=303,
        )

    return templates.TemplateResponse(
        request=request,
        name="faculty_leave.html",
        context={
            "current_user": user,
        },
    )


# ------------------------------------------------------------
# Get Faculty Leave Requests
# ------------------------------------------------------------

@router.get("/api/faculty/leaves")
def get_faculty_leaves(request: Request):

    user = require_faculty(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Faculty login required.",
        )

    db = get_connection()

    try:

        rows = db.execute(
            """
            SELECT
                lr.id,
                lr.timetable_id,
                lr.lecture_date,
                lr.reason,
                lr.status,
                lr.submitted_at,
                lr.reviewed_at,

                sub.name AS subject_name,
                sub.code AS subject_code,

                t.start_time,
                t.end_time,

                sp.roll_number,
                sp.name AS student_name,

                d.name AS division_name

            FROM leave_requests lr

            JOIN timetable t
                ON t.id = lr.timetable_id

            JOIN subjects sub
                ON sub.id = t.subject_id

            JOIN divisions d
                ON d.id = t.division_id

            JOIN faculty_assignments fa
                ON fa.subject_id = t.subject_id
               AND fa.division_id = t.division_id
               AND fa.faculty_id = ?
               AND fa.faculty_id = ?

            JOIN student_profiles sp
                ON sp.id = lr.student_id

            ORDER BY
                CASE
                    WHEN lr.status = 'Pending Leave'
                    THEN 0
                    ELSE 1
                END,
                lr.lecture_date,
                lr.id DESC
            """,
            (user["id"],),
        ).fetchall()

    finally:
        db.close()

    return {
        "leaves": [
            dict(row)
            for row in rows
        ]
    }


# ------------------------------------------------------------
# Decide Leave
# ------------------------------------------------------------

@router.post(
    "/api/faculty/leaves/{leave_id}/decision"
)
def decide_leave(
    leave_id: int,
    data: LeaveDecision,
    request: Request,
):

    user = require_faculty(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Faculty login required.",
        )

    decision = data.status.strip().lower()

    if decision in (
        "approved",
        "approved leave",
    ):
        new_status = LEAVE_APPROVED

    elif decision in (
        "rejected",
        "rejected leave",
    ):
        new_status = LEAVE_REJECTED

    else:
        raise HTTPException(
            status_code=400,
            detail="Status must be Approved or Rejected.",
        )

    db = get_connection()

    try:

        # --------------------------------------------------------
        # Verify that this faculty teaches the timetable entry
        # --------------------------------------------------------

        leave = db.execute(
            """
            SELECT
                lr.id,
                lr.status

            FROM leave_requests lr

            JOIN timetable t
                ON t.id = lr.timetable_id

            JOIN faculty_assignments fa
                ON fa.subject_id = t.subject_id
               AND fa.division_id = t.division_id
               AND fa.faculty_id = ?
               AND fa.faculty_id = ?

            WHERE lr.id = ?
            """,
            (
                user["id"],
                leave_id,
            ),
        ).fetchone()

        if not leave:
            raise HTTPException(
                status_code=404,
                detail="Leave request not found.",
            )

        if leave["status"] != LEAVE_PENDING:
            raise HTTPException(
                status_code=400,
                detail="This leave has already been reviewed.",
            )

        # --------------------------------------------------------
        # Update decision
        # --------------------------------------------------------

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
                datetime.now().isoformat(
                    timespec="seconds"
                ),
                user["id"],
                leave_id,
            ),
        )

        db.commit()

    finally:
        db.close()

    return {
        "success": True,
        "message": (
            f"Leave "
            f"{new_status.lower().replace(' leave', '')} "
            f"successfully."
        ),
    }

@router.get("/api/timetable")
def get_faculty_timetable(request: Request):
    user = require_faculty(request)

    conn = get_connection()
    try:
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
            LEFT JOIN subjects s
                ON t.subject_id = s.id
            LEFT JOIN divisions d
                ON t.division_id = d.id
            WHERE t.faculty_id = ?
              AND t.day_of_week BETWEEN 0 AND 5
            ORDER BY t.day_of_week, t.start_time
            """,
            (user["id"],)
        ).fetchall()

        day_names = {
            0: "Monday",
            1: "Tuesday",
            2: "Wednesday",
            3: "Thursday",
            4: "Friday",
            5: "Saturday",
        }

        timetable = []

        for row in rows:
            timetable.append({
                "id": row["id"],
                "day_of_week": row["day_of_week"],
                "day": day_names[row["day_of_week"]],
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "entry_type": row["entry_type"],
                "title": row["title"],
                "subject_name": row["subject_name"],
                "subject_code": row["subject_code"],
                "division_name": row["division_name"],
            })

        return {
            "faculty_id": user["id"],
            "timetable": timetable
        }

    finally:
        conn.close()

class StartAttendanceRequest(BaseModel):
    timetable_id: int


@router.post("/api/attendance/start")
def start_attendance_session(
    request: Request,
    data: StartAttendanceRequest,
):
    user = require_faculty(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Faculty login required."
        )

    conn = get_connection()

    try:
        # --------------------------------------------------
        # Get timetable entry
        # --------------------------------------------------

        timetable = conn.execute(
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
            (data.timetable_id,),
        ).fetchone()

        if timetable is None:
            raise HTTPException(
                status_code=404,
                detail="Timetable entry not found."
            )

        # --------------------------------------------------
        # Verify timetable belongs to logged-in faculty
        # --------------------------------------------------

        if timetable["faculty_id"] != user["id"]:
            raise HTTPException(
                status_code=403,
                detail="This timetable entry is not assigned to you."
            )

        # --------------------------------------------------
        # Only actual academic lectures can start attendance
        # --------------------------------------------------

        if timetable["entry_type"] not in ("LECTURE", "LAB"):
            raise HTTPException(
                status_code=400,
                detail="Attendance cannot be started for this timetable entry."
            )

        # --------------------------------------------------
        # Current date/time
        # --------------------------------------------------

        now = datetime.now()

        # Python weekday:
        # Monday = 0 ... Saturday = 5 ... Sunday = 6

        if now.weekday() != timetable["day_of_week"]:
            raise HTTPException(
                status_code=400,
                detail="This lecture is not scheduled for today."
            )

        current_time = now.strftime("%H:%M")
        lecture_date = now.strftime("%Y-%m-%d")

        # --------------------------------------------------
        # Check lecture time
        # --------------------------------------------------

        if current_time < timetable["start_time"]:
            raise HTTPException(
                status_code=400,
                detail="The lecture has not started yet."
            )

        if current_time > timetable["end_time"]:
            raise HTTPException(
                status_code=400,
                detail="The lecture time has already ended."
            )

        # --------------------------------------------------
        # Check whether session already exists
        # --------------------------------------------------

        existing_session = conn.execute(
            """
            SELECT id
            FROM attendance_sessions
            WHERE timetable_id = ?
              AND lecture_date = ?
            """,
            (
                timetable["id"],
                lecture_date,
            ),
        ).fetchone()

        if existing_session:
            raise HTTPException(
                status_code=409,
                detail="Attendance session already exists for this lecture."
            )

        # --------------------------------------------------
        # Get trusted college location
        # --------------------------------------------------

        college = conn.execute(
            """
            SELECT
                latitude,
                longitude,
                radius_meters
            FROM college_settings
            WHERE id = 1
            """
        ).fetchone()

        if college is None:
            raise HTTPException(
                status_code=400,
                detail="College location has not been configured."
            )

        # --------------------------------------------------
        # Create attendance session
        # --------------------------------------------------

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
                user["id"],
                timetable["subject_id"],
                timetable["division_id"],
                started_at,
                college["latitude"],
                college["longitude"],
                college["radius_meters"],
                timetable["id"],
                lecture_date,
            ),
        )

        session_id = cursor.lastrowid

        # --------------------------------------------------
        # Generate first QR token
        # --------------------------------------------------

        raw_token = secrets.token_urlsafe(32)

        token_hash = hashlib.sha256(
            raw_token.encode()
        ).hexdigest()

        valid_from = now.isoformat(timespec="seconds")

        expires_at = (
            now.timestamp() + 30
        )

        expires_datetime = datetime.fromtimestamp(
            expires_at
        )

        conn.execute(
            """
            INSERT INTO qr_tokens (
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
                valid_from,
                expires_datetime.isoformat(
                    timespec="seconds"
                ),
            ),
        )

        conn.commit()

        return {
            "success": True,
            "session_id": session_id,
            "timetable_id": timetable["id"],
            "lecture_date": lecture_date,
            "started_at": started_at,
            "qr_token": raw_token,
            "qr_expires_at": expires_datetime.isoformat(
                timespec="seconds"
            ),
        }

    finally:
        conn.close()