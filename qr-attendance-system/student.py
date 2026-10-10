
from datetime import date, datetime, time, timedelta
from math import radians, sin, cos, sqrt, atan2
import hashlib
import sqlite3

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from templating import templates
from pydantic import BaseModel, Field

from database import get_connection
from auth import get_current_user


router = APIRouter(prefix="/student", tags=["Student"])

PASS_PERCENT = 75
MAX_LEAVE_REASON_LENGTH = 500

DAY_NAMES = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}


# ============================================================
# REQUEST MODELS
# ============================================================

class AttendanceMarkRequest(BaseModel):
    token: str = Field(min_length=1, max_length=500)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class LeaveRequest(BaseModel):
    timetable_id: int = Field(gt=0)
    lecture_date: str
    reason: str = Field(min_length=1, max_length=MAX_LEAVE_REASON_LENGTH)


# ============================================================
# COMMON HELPERS
# ============================================================

def require_student(request: Request):
    """Return the authenticated student session, or None."""
    user = get_current_user(request)

    if not user or user.get("role") != "student":
        return None

    return user


def parse_datetime(value):
    """Parse a stored ISO datetime safely."""
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def parse_time(value):
    """Accept timetable times stored as HH:MM or HH:MM:SS."""
    if not value:
        return None

    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue

    return None


def haversine_distance(lat1, lon1, lat2, lon2):
    """Return the distance in metres between two coordinates."""
    earth_radius = 6_371_000

    lat1 = radians(lat1)
    lat2 = radians(lat2)
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1)
        * cos(lat2)
        * sin(dlon / 2) ** 2
    )

    # Protect against minor floating-point rounding errors.
    a = max(0.0, min(1.0, a))

    return earth_radius * 2 * atan2(
        sqrt(a),
        sqrt(1 - a),
    )


def get_active_student(db, user_id):
    """Fetch an active student profile."""
    return db.execute(
        """
        SELECT
            id,
            name,
            email,
            roll_number,
            department_id,
            semester_id,
            division_id,
            is_active
        FROM student_profiles
        WHERE id = ?
          AND is_active = 1
        """,
        (user_id,),
    ).fetchone()


def parse_lecture_date(value):
    """Accept only a valid YYYY-MM-DD date."""
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Invalid lecture date. Use YYYY-MM-DD.",
        )

    if parsed.isoformat() != value:
        raise HTTPException(
            status_code=400,
            detail="Invalid lecture date. Use YYYY-MM-DD.",
        )

    return parsed


def _percent_info(present: int, absent: int) -> dict:
    """
    Calculate attendance percentage.

    Approved leave is included in present.
    All counted lectures remain in the denominator.
    """
    total = present + absent

    if total == 0:
        return {
            "percentage": None,
            "warning": False,
            "classes_needed": 0,
            "can_miss": 0,
        }

    percentage = round(present * 100 / total, 2)
    warning = present * 100 < PASS_PERCENT * total

    # Minimum consecutive classes to attend to reach 75%.
    classes_needed = (
        max(0, 3 * total - 4 * present)
        if warning
        else 0
    )

    # Maximum future classes that may be missed while
    # keeping attendance at or above 75%.
    can_miss = (
        max(0, (4 * present - 3 * total) // 3)
        if not warning
        else 0
    )

    return {
        "percentage": percentage,
        "warning": warning,
        "classes_needed": classes_needed,
        "can_miss": can_miss,
    }


# ============================================================
# STUDENT PAGES
# ============================================================

@router.get("/mark", response_class=HTMLResponse)
@router.get("/student/mark", response_class=HTMLResponse,
            include_in_schema=False)
def student_mark_page(request: Request):
    user = require_student(request)

    if not user:
        return RedirectResponse("/student/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="student_mark.html",
        context={"current_user": user},
    )


@router.get("/attendance", response_class=HTMLResponse)
@router.get("/student/attendance", response_class=HTMLResponse,
            include_in_schema=False)
def student_attendance_page(request: Request):
    user = require_student(request)

    if not user:
        return RedirectResponse("/student/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="student_attendance.html",
        context={"current_user": user},
    )


@router.get("/leave", response_class=HTMLResponse)
@router.get("/student/leave", response_class=HTMLResponse,
            include_in_schema=False)
def student_leave_page(request: Request):
    user = require_student(request)

    if not user:
        return RedirectResponse("/student/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="student_leave.html",
        context={"current_user": user},
    )


# ============================================================
# ATTENDANCE HISTORY AND PERCENTAGE
# ============================================================

@router.get("/api/attendance")
@router.get("/api/student/attendance", include_in_schema=False)
def student_attendance(request: Request):
    user = require_student(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Student login required.",
        )

    db = get_connection()

    try:
        student = get_active_student(db, user["id"])

        if not student:
            raise HTTPException(
                status_code=404,
                detail="Active student profile not found.",
            )

        rows = db.execute(
            """
            SELECT
                s.id AS session_id,
                s.started_at,
                s.closed_at,
                s.lecture_date,

                sub.id AS subject_id,
                sub.name AS subject_name,
                sub.code AS subject_code,

                ar.status AS record_status,
                ar.method,

                lr.status AS leave_status

            FROM attendance_sessions s

            JOIN subjects sub
                ON sub.id = s.subject_id

            LEFT JOIN attendance_records ar
                ON ar.session_id = s.id
               AND ar.student_id = ?

            LEFT JOIN leave_requests lr
                ON lr.student_id = ?
               AND lr.timetable_id = s.timetable_id
               AND lr.lecture_date = s.lecture_date

            WHERE s.division_id = ?
              AND s.is_active = 0

            ORDER BY
                COALESCE(s.lecture_date, s.closed_at, s.started_at)
                DESC,
                s.id DESC
            """,
            (
                student["id"],
                student["id"],
                student["division_id"],
            ),
        ).fetchall()

        history = []
        subject_data = {}

        total_present = 0
        total_absent = 0
        total_leave = 0

        for row in rows:
            # An actual present record takes priority.
            if row["record_status"] == "present":
                status = "present"
            elif row["leave_status"] == "Approved Leave":
                status = "leave"
            else:
                status = "absent"

            history_date = (
                row["lecture_date"]
                or row["closed_at"]
                or row["started_at"]
            )

            history.append({
                "session_id": row["session_id"],
                "date": history_date,
                "subject_name": row["subject_name"],
                "subject_code": row["subject_code"],
                "status": status,
                "leave_status": row["leave_status"],
                "method": row["method"] or "-",
            })

            subject_id = row["subject_id"]

            if subject_id not in subject_data:
                subject_data[subject_id] = {
                    "subject_name": row["subject_name"],
                    "subject_code": row["subject_code"],
                    "total": 0,
                    "present": 0,
                    "absent": 0,
                    "leave": 0,
                }

            item = subject_data[subject_id]
            item["total"] += 1

            if status == "present":
                item["present"] += 1
                total_present += 1
            elif status == "leave":
                # Approved leave counts as present.
                item["present"] += 1
                item["leave"] += 1
                total_present += 1
                total_leave += 1
            else:
                item["absent"] += 1
                total_absent += 1

        subjects = []

        for item in subject_data.values():
            item.update(
                _percent_info(item["present"], item["absent"])
            )
            subjects.append(item)

        subjects.sort(
            key=lambda item: (item["subject_name"] or "").lower()
        )

        overall = {
            "total": len(rows),
            "present": total_present,
            "absent": total_absent,
            "leave": total_leave,
        }
        overall.update(_percent_info(total_present, total_absent))

        return {
            "overall": overall,
            "subjects": subjects,
            "history": history,
        }

    finally:
        db.close()


# ============================================================
# MARK ATTENDANCE USING QR
# ============================================================

@router.post("/api/attendance/mark")
@router.post("/api/student/attendance/mark", include_in_schema=False)
def mark_attendance(
    request: Request,
    data: AttendanceMarkRequest,
):
    user = require_student(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Student login required.",
        )

    db = get_connection()

    try:
        student = get_active_student(db, user["id"])

        if not student:
            raise HTTPException(
                status_code=404,
                detail="Active student profile not found.",
            )

        token = data.token.strip()

        if not token:
            raise HTTPException(
                status_code=400,
                detail="Please enter the QR token.",
            )

        token_hash = hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

        token_row = db.execute(
            """
            SELECT
                qt.id AS token_id,
                qt.session_id,
                qt.valid_from,
                qt.expires_at,

                s.subject_id,
                s.division_id,
                s.is_active,
                s.timetable_id,
                s.lecture_date,

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
                detail="Invalid QR code.",
            )

        if token_row["is_active"] != 1:
            raise HTTPException(
                status_code=400,
                detail="This attendance session is closed.",
            )

        now = datetime.now()
        valid_from = parse_datetime(token_row["valid_from"])
        expires_at = parse_datetime(token_row["expires_at"])

        if valid_from is None or expires_at is None:
            raise HTTPException(
                status_code=400,
                detail="The QR code has an invalid validity period.",
            )

        if now < valid_from:
            raise HTTPException(
                status_code=400,
                detail="This QR code is not active yet.",
            )

        if now > expires_at:
            raise HTTPException(
                status_code=400,
                detail=(
                    "QR code has expired. "
                    "Please use the current QR code."
                ),
            )

        if student["division_id"] != token_row["division_id"]:
            raise HTTPException(
                status_code=403,
                detail="You are not part of this class.",
            )

        # Use the college location configured by the administrator.
        college = db.execute(
            """
            SELECT latitude, longitude, radius_meters
            FROM college_settings
            WHERE id = 1
            """
        ).fetchone()

        if (
            not college
            or college["latitude"] is None
            or college["longitude"] is None
        ):
            raise HTTPException(
                status_code=500,
                detail="The campus location has not been set up yet. Please tell your administrator.",
            )

        distance = haversine_distance(
            college["latitude"],
            college["longitude"],
            data.latitude,
            data.longitude,
        )

        radius = college["radius_meters"]

        if radius is None or radius <= 0:
            radius = 100

        if distance > radius:
            raise HTTPException(
                status_code=403,
                detail=(
                    "You are outside the campus area. Move closer to your "
                    "classroom and try again."
                ),
            )

        try:
            db.execute(
                """
                INSERT INTO attendance_records
                (
                    session_id,
                    student_id,
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
                    student["id"],
                    now.isoformat(timespec="seconds"),
                    data.latitude,
                    data.longitude,
                    distance,
                ),
            )
            db.commit()

        except sqlite3.IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Attendance has already been marked for this session.",
            )

        return {
            "success": True,
            "message": "Attendance marked successfully!",
            "subject": token_row["subject_name"],
            "subject_code": token_row["subject_code"],
        }

    finally:
        db.close()


# ============================================================
# ELIGIBLE FUTURE LEAVE LECTURES
# ============================================================

@router.get("/api/leave/eligible")
@router.get("/api/student/leave/eligible", include_in_schema=False)
def eligible_leave_sessions(request: Request):
    user = require_student(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Student login required.",
        )

    db = get_connection()

    try:
        student = get_active_student(db, user["id"])

        if not student:
            raise HTTPException(
                status_code=404,
                detail="Active student profile not found.",
            )

        today = date.today()
        now = datetime.now()

        timetable_rows = db.execute(
            """
            SELECT
                t.id AS timetable_id,
                t.day_of_week,
                t.start_time,
                t.end_time,
                t.entry_type,
                t.title,

                sub.id AS subject_id,
                sub.name AS subject_name,
                sub.code AS subject_code,

                fp.name AS faculty_name

            FROM timetable t

            LEFT JOIN subjects sub
                ON sub.id = t.subject_id

            LEFT JOIN faculty_profiles fp
                ON fp.id = t.faculty_id

            WHERE t.division_id = ?
              AND t.entry_type IN ('LECTURE', 'LAB')
              AND t.day_of_week BETWEEN 0 AND 6

            ORDER BY t.day_of_week, t.start_time
            """,
            (student["division_id"],),
        ).fetchall()

        eligible = []

        for row in timetable_rows:
            start_time = parse_time(row["start_time"])

            if start_time is None:
                continue

            days_ahead = (row["day_of_week"] - today.weekday()) % 7
            occurrence_date = today + timedelta(days=days_ahead)

            occurrence_datetime = datetime.combine(
                occurrence_date,
                start_time,
            )

            # Do not offer a lecture that has already started.
            if occurrence_datetime <= now:
                occurrence_date += timedelta(days=7)

            lecture_date = occurrence_date.isoformat()

            existing_session = db.execute(
                """
                SELECT id
                FROM attendance_sessions
                WHERE timetable_id = ?
                  AND lecture_date = ?
                LIMIT 1
                """,
                (row["timetable_id"], lecture_date),
            ).fetchone()

            if existing_session:
                continue

            existing_leave = db.execute(
                """
                SELECT id
                FROM leave_requests
                WHERE student_id = ?
                  AND timetable_id = ?
                  AND lecture_date = ?
                LIMIT 1
                """,
                (
                    student["id"],
                    row["timetable_id"],
                    lecture_date,
                ),
            ).fetchone()

            if existing_leave:
                continue

            eligible.append({
                "timetable_id": row["timetable_id"],
                "lecture_date": lecture_date,
                "day_of_week": row["day_of_week"],
                "day": DAY_NAMES.get(row["day_of_week"], "Unknown"),
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "entry_type": row["entry_type"],
                "title": row["title"],
                "subject_id": row["subject_id"],
                "subject_name": row["subject_name"],
                "subject_code": row["subject_code"],
                "faculty_name": row["faculty_name"],
            })

        eligible.sort(
            key=lambda item: (
                item["lecture_date"],
                item["start_time"],
            )
        )

        return {"lectures": eligible}

    finally:
        db.close()


# ============================================================
# SUBMIT A FUTURE LEAVE REQUEST
# ============================================================

@router.post("/api/leave")
@router.post("/api/student/leave", include_in_schema=False)
def submit_leave(
    request: Request,
    data: LeaveRequest,
):
    user = require_student(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Student login required.",
        )

    reason = data.reason.strip()

    if not reason:
        raise HTTPException(
            status_code=400,
            detail="Reason is required.",
        )

    if len(reason) > MAX_LEAVE_REASON_LENGTH:
        raise HTTPException(
            status_code=400,
            detail="Reason must be 500 characters or fewer.",
        )

    lecture_date = parse_lecture_date(data.lecture_date)
    now = datetime.now()

    if lecture_date < now.date():
        raise HTTPException(
            status_code=400,
            detail="Leave can only be requested for a future lecture.",
        )

    db = get_connection()

    try:
        student = get_active_student(db, user["id"])

        if not student:
            raise HTTPException(
                status_code=404,
                detail="Active student profile not found.",
            )

        timetable = db.execute(
            """
            SELECT
                t.id,
                t.division_id,
                t.subject_id,
                t.day_of_week,
                t.start_time,
                t.end_time,
                t.entry_type,

                sub.name AS subject_name,
                sub.code AS subject_code

            FROM timetable t

            JOIN subjects sub
                ON sub.id = t.subject_id

            WHERE t.id = ?
              AND t.division_id = ?
              AND t.entry_type IN ('LECTURE', 'LAB')
            """,
            (
                data.timetable_id,
                student["division_id"],
            ),
        ).fetchone()

        if not timetable:
            raise HTTPException(
                status_code=404,
                detail="This timetable lecture was not found.",
            )

        if lecture_date.weekday() != timetable["day_of_week"]:
            raise HTTPException(
                status_code=400,
                detail="The selected date does not match this timetable lecture.",
            )

        start_time = parse_time(timetable["start_time"])

        if start_time is None:
            raise HTTPException(
                status_code=500,
                detail="The timetable contains an invalid start time.",
            )

        lecture_datetime = datetime.combine(lecture_date, start_time)

        if lecture_datetime <= now:
            raise HTTPException(
                status_code=400,
                detail="This lecture has already started or passed.",
            )

        existing_session = db.execute(
            """
            SELECT id
            FROM attendance_sessions
            WHERE timetable_id = ?
              AND lecture_date = ?
            LIMIT 1
            """,
            (
                data.timetable_id,
                lecture_date.isoformat(),
            ),
        ).fetchone()

        if existing_session:
            raise HTTPException(
                status_code=409,
                detail="Attendance for this lecture has already started.",
            )

        existing_leave = db.execute(
            """
            SELECT id
            FROM leave_requests
            WHERE student_id = ?
              AND timetable_id = ?
              AND lecture_date = ?
            LIMIT 1
            """,
            (
                student["id"],
                data.timetable_id,
                lecture_date.isoformat(),
            ),
        ).fetchone()

        if existing_leave:
            raise HTTPException(
                status_code=409,
                detail="Leave has already been submitted for this lecture.",
            )

        try:
            db.execute(
                """
                INSERT INTO leave_requests
                (
                    student_id,
                    timetable_id,
                    lecture_date,
                    reason,
                    status,
                    submitted_at
                )
                VALUES (?, ?, ?, ?, 'Pending Leave', ?)
                """,
                (
                    student["id"],
                    data.timetable_id,
                    lecture_date.isoformat(),
                    reason,
                    now.isoformat(timespec="seconds"),
                ),
            )
            db.commit()

        except sqlite3.IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Leave has already been submitted for this lecture.",
            )

        return {
            "success": True,
            "message": "Leave request submitted successfully.",
        }

    finally:
        db.close()


# ============================================================
# STUDENT LEAVE HISTORY
# ============================================================

@router.get("/api/leave")
@router.get("/api/student/leave", include_in_schema=False)
def get_student_leaves(request: Request):
    user = require_student(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Student login required.",
        )

    db = get_connection()

    try:
        student = get_active_student(db, user["id"])

        if not student:
            raise HTTPException(
                status_code=404,
                detail="Active student profile not found.",
            )

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

                t.day_of_week,
                t.start_time,
                t.end_time,
                t.entry_type,

                sub.name AS subject_name,
                sub.code AS subject_code,

                fp.name AS faculty_name

            FROM leave_requests lr

            JOIN timetable t
                ON t.id = lr.timetable_id

            LEFT JOIN subjects sub
                ON sub.id = t.subject_id

            LEFT JOIN faculty_profiles fp
                ON fp.id = t.faculty_id

            WHERE lr.student_id = ?

            ORDER BY
                lr.lecture_date DESC,
                t.start_time DESC,
                lr.id DESC
            """,
            (student["id"],),
        ).fetchall()

        leaves = []

        for row in rows:
            item = dict(row)
            item["day"] = DAY_NAMES.get(
                item["day_of_week"],
                "Unknown",
            )
            leaves.append(item)

        return {"leaves": leaves}

    finally:
        db.close()


# ============================================================
# STUDENT TIMETABLE PAGE
# ============================================================

@router.get("/timetable", response_class=HTMLResponse)
@router.get("/student/timetable", response_class=HTMLResponse,
            include_in_schema=False)
def student_timetable(request: Request):
    student_user = require_student(request)

    if not student_user:
        return RedirectResponse("/student/login", status_code=303)

    db = get_connection()

    try:
        student = get_active_student(db, student_user["id"])

        if not student:
            return RedirectResponse("/student/login", status_code=303)

        # A student sees only entries assigned to their own division.
        rows = db.execute(
            """
            SELECT
                t.id,
                t.day_of_week,
                t.start_time,
                t.end_time,
                t.entry_type,
                t.title,

                sub.name AS subject_name,
                sub.code AS subject_code,

                sem.number AS semester_number,
                dep.code AS department_code,

                fp.name AS faculty_name

            FROM timetable t

            LEFT JOIN subjects sub
                ON sub.id = t.subject_id

            LEFT JOIN divisions div
                ON div.id = t.division_id

            LEFT JOIN semesters sem
                ON sem.id = div.semester_id

            LEFT JOIN departments dep
                ON dep.id = div.department_id

            LEFT JOIN faculty_profiles fp
                ON fp.id = t.faculty_id

            WHERE t.division_id = ?

            ORDER BY t.day_of_week, t.start_time
            """,
            (student["division_id"],),
        ).fetchall()

        timetable = []

        for row in rows:
            item = dict(row)
            item["day"] = DAY_NAMES.get(
                item["day_of_week"],
                "Unknown",
            )
            timetable.append(item)

    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="student_timetable.html",
        context={
            "current_user": student_user,
            "timetable": timetable,
        },
    )


# ============================================================
# STUDENT TIMETABLE API
# ============================================================

@router.get("/api/timetable")
def get_student_timetable(request: Request):
    user = require_student(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Student login required.",
        )

    db = get_connection()

    try:
        student = get_active_student(db, user["id"])

        if not student:
            raise HTTPException(
                status_code=404,
                detail="Active student profile not found.",
            )

        rows = db.execute(
            """
            SELECT
                t.id,
                t.day_of_week,
                t.start_time,
                t.end_time,
                t.entry_type,
                t.title,

                sub.name AS subject_name,
                sub.code AS subject_code,

                fp.name AS faculty_name,
                div.name AS division_name

            FROM timetable t

            LEFT JOIN subjects sub
                ON sub.id = t.subject_id

            LEFT JOIN faculty_profiles fp
                ON fp.id = t.faculty_id

            LEFT JOIN divisions div
                ON div.id = t.division_id

            WHERE t.division_id = ?
              AND t.day_of_week BETWEEN 0 AND 6

            ORDER BY t.day_of_week, t.start_time
            """,
            (student["division_id"],),
        ).fetchall()

        timetable = []

        for row in rows:
            timetable.append({
                "id": row["id"],
                "day_of_week": row["day_of_week"],
                "day": DAY_NAMES.get(
                    row["day_of_week"],
                    "Unknown",
                ),
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "entry_type": row["entry_type"],
                "title": row["title"],
                "subject_name": row["subject_name"],
                "subject_code": row["subject_code"],
                "faculty_name": row["faculty_name"],
                "division_name": row["division_name"],
            })

        return {
            "student_id": student["id"],
            "division_id": student["division_id"],
            "timetable": timetable,
        }

    finally:
        db.close()