from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2
import hashlib
import sqlite3

# from app.database import get_db
# from app.security import require_role
from database import get_connection
from auth import get_current_user

router = APIRouter()

templates = Jinja2Templates(directory="templates")


class AttendanceMarkRequest(BaseModel):
    token: str
    latitude: float
    longitude: float


def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000

    lat1 = radians(lat1)
    lat2 = radians(lat2)

    dlat = lat2 - lat1
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    )

    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def require_student(request: Request):
    user = get_current_user(request)

    if not user or user["role"] != "student":
        return None

    return user


@router.get("/student/mark", response_class=HTMLResponse)
def student_mark_page(request: Request):
    user = require_student(request)

    if not user:
        return RedirectResponse("/student/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="student_mark.html",
        context={"current_user": user},
    )


PASS_PERCENT = 75


def _percent_info(present: int, absent: int) -> dict:
    """
    Attendance maths shared by the overall and subject-wise views.

    Approved-leave sessions are excused, so they are not part of
    present/absent here (the caller passes them separately).
    """
    counted = present + absent

    if counted == 0:
        return {
            "percentage": None,
            "warning": False,
            "classes_needed": 0,
            "can_miss": 0,
        }

    percentage = round(present * 100 / counted, 2)

    # Integer maths so exactly 75% never triggers a false warning.
    warning = present * 100 < PASS_PERCENT * counted

    # Present-in-a-row needed to get back to 75%: n >= 3*counted - 4*present
    classes_needed = max(0, 3 * counted - 4 * present) if warning else 0

    # Classes that can still be missed while staying at/above 75%.
    can_miss = 0 if warning else max(0, (4 * present - 3 * counted) // 3)

    return {
        "percentage": percentage,
        "warning": warning,
        "classes_needed": classes_needed,
        "can_miss": can_miss,
    }


@router.get("/api/student/attendance")
def student_attendance(request: Request):
    user = require_student(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Student login required."
        )

    db = get_connection()

    try:
        # Every closed session of the student's division, with the
        # student's record and leave request (if any).
        rows = db.execute(
            """
            SELECT
                s.id AS session_id,
                s.started_at,
                s.closed_at,
                sub.id AS subject_id,
                sub.name AS subject_name,
                sub.code AS subject_code,
                ar.status AS record_status,
                ar.method,
                lr.status AS leave_status
            FROM student_profiles sp
            JOIN attendance_sessions s
                ON s.division_id = sp.division_id
                AND s.is_active = 0
            JOIN subjects sub
                ON sub.id = s.subject_id
            LEFT JOIN attendance_records ar
                ON ar.session_id = s.id
                AND ar.student_user_id = sp.user_id
            LEFT JOIN leave_requests lr
                ON lr.session_id = s.id
                AND lr.student_user_id = sp.user_id
            WHERE sp.user_id = ?
            ORDER BY COALESCE(s.closed_at, s.started_at) DESC, s.id DESC
            """,
            (user["id"],),
        ).fetchall()
    finally:
        db.close()

    history = []
    subject_data = {}
    present = absent = leave = 0

    for row in rows:
        if row["record_status"] == "present":
            status = "present"
        elif row["leave_status"] == "Approved Leave":
            status = "leave"
        else:
            status = "absent"

        history.append(
            {
                "session_id": row["session_id"],
                "date": row["closed_at"] or row["started_at"],
                "subject_name": row["subject_name"],
                "subject_code": row["subject_code"],
                "status": status,
                "leave_status": row["leave_status"],
                "method": row["method"] or "-",
            }
        )

        sid = row["subject_id"]

        if sid not in subject_data:
            subject_data[sid] = {
                "subject_name": row["subject_name"],
                "subject_code": row["subject_code"],
                "total": 0,
                "present": 0,
                "absent": 0,
                "leave": 0,
            }

        item = subject_data[sid]
        item["total"] += 1
        item[status] += 1

        if status == "present":
            present += 1
        elif status == "leave":
            leave += 1
        else:
            absent += 1

    subjects = []

    for item in subject_data.values():
        item.update(_percent_info(item["present"], item["absent"]))
        subjects.append(item)

    subjects.sort(key=lambda x: x["subject_name"].lower())

    overall = {
        "total": len(rows),
        "present": present,
        "absent": absent,
        "leave": leave,
    }
    overall.update(_percent_info(present, absent))

    return {
        "overall": overall,
        "subjects": subjects,
        "history": history,
    }


@router.post("/api/student/attendance/mark")
def mark_attendance(request: Request, data: AttendanceMarkRequest):
    user = require_student(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Student login required."
        )

    db = get_connection()

    try:
        return _mark_attendance(db, user, data)
    finally:
        db.close()


def _mark_attendance(db, user, data: AttendanceMarkRequest):

    token = data.token.strip()

    if not token:
        raise HTTPException(status_code=400, detail="Please enter the QR token.")

    # Validate coordinates
    if not (-90 <= data.latitude <= 90 and -180 <= data.longitude <= 180):
        raise HTTPException(
            status_code=400,
            detail="Invalid location coordinates."
        )

    # Get student's class
    student = db.execute(
        """
        SELECT user_id, division_id, roll_number
        FROM student_profiles
        WHERE user_id = ?
        """,
        (user["id"],),
    ).fetchone()

    if not student:
        raise HTTPException(
            status_code=404,
            detail="Student profile not found."
        )

    # Hash submitted token
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    # Find token and its session
    token_row = db.execute(
        """
        SELECT
            qt.id AS token_id,
            qt.session_id,
            qt.valid_from,
            qt.expires_at,
            s.subject_id,
            s.division_id,
            s.latitude AS session_latitude,
            s.longitude AS session_longitude,
            s.radius_meters,
            s.is_active,
            sub.name AS subject_name,
            sub.code AS subject_code
        FROM qr_tokens qt
        JOIN attendance_sessions s
            ON s.id = qt.session_id
        JOIN subjects sub
            ON sub.id = s.subject_id
        WHERE qt.token_hash = ?
        ORDER BY qt.id DESC
        LIMIT 1
        """,
        (token_hash,),
    ).fetchone()

    if not token_row:
        raise HTTPException(
            status_code=400,
            detail="Invalid QR code."
        )

    # Session must still be active
    if token_row["is_active"] != 1:
        raise HTTPException(
            status_code=400,
            detail="This attendance session is closed."
        )

    # Check token expiry
    now = datetime.now()
    expires_at = datetime.fromisoformat(token_row["expires_at"])

    if now > expires_at:
        raise HTTPException(
            status_code=400,
            detail="QR code has expired. Please use the current QR code."
        )

    # Student must belong to the same class/division
    if student["division_id"] != token_row["division_id"]:
        raise HTTPException(
            status_code=403,
            detail="You are not part of this class."
        )

    # Calculate distance from faculty/session location
    distance = haversine_distance(
        token_row["session_latitude"],
        token_row["session_longitude"],
        data.latitude,
        data.longitude,
    )

    radius = token_row["radius_meters"] or 100

    if distance > radius:
        raise HTTPException(
            status_code=403,
            detail=(
                f"You are outside the allowed attendance area. "
                f"Distance: {round(distance)} m, allowed: {round(radius)} m."
            ),
        )

    # Duplicate prevention
    existing = db.execute(
        """
        SELECT id
        FROM attendance_records
        WHERE session_id = ?
          AND student_user_id = ?
        """,
        (token_row["session_id"], user["id"]),
    ).fetchone()

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Attendance already marked for this session."
        )

    # Mark present
    try:
        db.execute(
        """
        INSERT INTO attendance_records
        (
            session_id,
            student_user_id,
            status,
            method,
            marked_at,
            marked_by,
            latitude,
            longitude,
            distance_m
        )
        VALUES (?, ?, 'present', 'qr', ?, NULL, ?, ?, ?)
        """,
        (
            token_row["session_id"],
            user["id"],
            now.isoformat(timespec="seconds"),
            data.latitude,
            data.longitude,
            distance,
        ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=400,
            detail="Attendance already marked for this session."
        )

    return {
        "success": True,
        "message": "Attendance marked successfully!",
        "subject": token_row["subject_name"],
        "subject_code": token_row["subject_code"],
        "distance_m": round(distance, 1),
    }

@router.get("/student/attendance", response_class=HTMLResponse)
def student_attendance_page(request: Request):

    user = require_student(request)

    if not user:
        return RedirectResponse("/student/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="student_attendance.html",
        context={"current_user": user},
    )


# ============================================================
# LEAVE REQUESTS
# ============================================================

class LeaveRequest(BaseModel):
    session_id: int
    reason: str


@router.get("/student/leave", response_class=HTMLResponse)
def student_leave_page(request: Request):

    user = require_student(request)

    if not user:
        return RedirectResponse("/student/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="student_leave.html",
        context={"current_user": user},
    )


@router.get("/api/student/leave/eligible")
def eligible_leave_sessions(request: Request):
    """
    Closed sessions where the student is absent and has not
    already applied for leave.
    """
    user = require_student(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Student login required."
        )

    db = get_connection()

    try:
        rows = db.execute(
            """
            SELECT
                s.id AS session_id,
                s.started_at,
                sub.name AS subject_name,
                sub.code AS subject_code
            FROM student_profiles sp
            JOIN attendance_sessions s
                ON s.division_id = sp.division_id
                AND s.is_active = 0
            JOIN subjects sub
                ON sub.id = s.subject_id
            WHERE sp.user_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM attendance_records ar
                  WHERE ar.session_id = s.id
                    AND ar.student_user_id = sp.user_id
                    AND ar.status = 'present'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM leave_requests lr
                  WHERE lr.session_id = s.id
                    AND lr.student_user_id = sp.user_id
              )
            ORDER BY s.started_at DESC, s.id DESC
            """,
            (user["id"],),
        ).fetchall()
    finally:
        db.close()

    return {"sessions": [dict(r) for r in rows]}


@router.post("/api/student/leave")
def submit_leave(request: Request, data: LeaveRequest):

    user = require_student(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Student login required."
        )

    reason = data.reason.strip()

    if not reason:
        raise HTTPException(
            status_code=400,
            detail="Reason is required."
        )

    if len(reason) > 500:
        raise HTTPException(
            status_code=400,
            detail="Reason must be 500 characters or fewer."
        )

    db = get_connection()

    try:
        session = db.execute(
            """
            SELECT s.id, s.is_active
            FROM attendance_sessions s
            JOIN student_profiles sp
                ON sp.division_id = s.division_id
            WHERE s.id = ?
              AND sp.user_id = ?
            """,
            (data.session_id, user["id"]),
        ).fetchone()

        if not session:
            raise HTTPException(
                status_code=404,
                detail="Attendance session not found."
            )

        if session["is_active"] == 1:
            raise HTTPException(
                status_code=400,
                detail="This session is still running. "
                       "You can request leave after it closes."
            )

        present = db.execute(
            """
            SELECT 1
            FROM attendance_records
            WHERE session_id = ?
              AND student_user_id = ?
              AND status = 'present'
            """,
            (data.session_id, user["id"]),
        ).fetchone()

        if present:
            raise HTTPException(
                status_code=400,
                detail="You were present in this session."
            )

        try:
            db.execute(
                """
                INSERT INTO leave_requests
                (student_user_id, session_id, reason, status, submitted_at)
                VALUES (?, ?, ?, 'Pending Leave', ?)
                """,
                (
                    user["id"],
                    data.session_id,
                    reason,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            db.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=400,
                detail="Leave already submitted for this session."
            )
    finally:
        db.close()

    return {
        "success": True,
        "message": "Leave request submitted successfully."
    }


@router.get("/api/student/leave")
def get_student_leaves(request: Request):

    user = require_student(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Student login required."
        )

    db = get_connection()

    try:
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
                s.started_at
            FROM leave_requests lr
            JOIN attendance_sessions s
                ON s.id = lr.session_id
            JOIN subjects sub
                ON sub.id = s.subject_id
            WHERE lr.student_user_id = ?
            ORDER BY lr.id DESC
            """,
            (user["id"],),
        ).fetchall()
    finally:
        db.close()

    return {"leaves": [dict(row) for row in rows]}

@router.get("/student/timetable", response_class=HTMLResponse)
def student_timetable(request: Request):
    student = require_student(request)

    conn = get_connection()
    try:
        profile = conn.execute(
            """
            SELECT division_id
            FROM student_profiles
            WHERE user_id = ?
            """,
            (student["id"],),
        ).fetchone()

        if profile is None:
            return RedirectResponse(
                url="/dashboard",
                status_code=303,
            )

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

                semesters.number AS semester_number,
                departments.code AS department_code,

                users.name AS faculty_name

            FROM timetable

            LEFT JOIN subjects
                ON subjects.id = timetable.subject_id

            LEFT JOIN divisions
                ON divisions.id = timetable.division_id

            LEFT JOIN semesters
                ON semesters.id = divisions.semester_id

            LEFT JOIN departments
                ON departments.id = divisions.department_id

            LEFT JOIN users
                ON users.id = timetable.faculty_user_id

            WHERE timetable.division_id = ?
               OR timetable.entry_type IN ('HOD_USE', 'OTHER')

            ORDER BY
                timetable.day_of_week,
                timetable.start_time
            """,
            (profile["division_id"],),
        ).fetchall()

    finally:
        conn.close()

    return templates.TemplateResponse(
        "student_timetable.html",
        {
            "request": request,
            "current_user": student,
            "timetable": timetable,
        },
    )