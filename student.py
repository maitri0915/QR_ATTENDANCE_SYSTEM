from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2
import hashlib
import sqlite3

from database import get_connection
from auth import get_current_user

router = APIRouter(prefix="/student")

templates = Jinja2Templates(directory="templates")


# ============================================================
# ATTENDANCE
# ============================================================

class AttendanceMarkRequest(BaseModel):
    token: str
    latitude: float
    longitude: float


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate distance between two latitude/longitude points
    using the Haversine formula.

    Returns distance in meters.
    """

    R = 6371000

    lat1 = radians(lat1)
    lat2 = radians(lat2)

    dlat = lat2 - lat1
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1)
        * cos(lat2)
        * sin(dlon / 2) ** 2
    )

    return R * 2 * atan2(
        sqrt(a),
        sqrt(1 - a)
    )


def require_student(request: Request):
    """
    Return the logged-in student session.

    Returns None if the user is not logged in
    as a student.
    """

    user = get_current_user(request)

    if not user or user["role"] != "student":
        return None

    return user


@router.get("/student/mark", response_class=HTMLResponse)
def student_mark_page(request: Request):

    user = require_student(request)

    if not user:
        return RedirectResponse(
            "/student/login",
            status_code=303
        )

    return templates.TemplateResponse(
        request=request,
        name="student_mark.html",
        context={
            "current_user": user
        },
    )


# ============================================================
# ATTENDANCE PERCENTAGE
# ============================================================

PASS_PERCENT = 75


def _percent_info(present: int, absent: int) -> dict:
    """
    Calculate attendance percentage.

    Approved Leave is counted as Present by the caller,
    therefore it is included in the present count.

    Every lecture remains part of the denominator.
    """

    counted = present + absent

    if counted == 0:
        return {
            "percentage": None,
            "warning": False,
            "classes_needed": 0,
            "can_miss": 0,
        }

    percentage = round(
        present * 100 / counted,
        2
    )

    warning = (
        present * 100
        < PASS_PERCENT * counted
    )

    # Number of future classes that must be attended
    # continuously to reach 75%.
    classes_needed = (
        max(
            0,
            3 * counted - 4 * present
        )
        if warning
        else 0
    )

    # Number of classes that can be missed while
    # remaining at or above 75%.
    can_miss = (
        0
        if warning
        else max(
            0,
            (4 * present - 3 * counted) // 3
        )
    )

    return {
        "percentage": percentage,
        "warning": warning,
        "classes_needed": classes_needed,
        "can_miss": can_miss,
    }


# ============================================================
# STUDENT ATTENDANCE HISTORY
# ============================================================

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

            FROM student_profiles sp

            JOIN attendance_sessions s
                ON s.division_id = sp.division_id
                AND s.is_active = 0

            JOIN subjects sub
                ON sub.id = s.subject_id

            LEFT JOIN attendance_records ar
                ON ar.session_id = s.id
                AND ar.student_id = sp.id

            LEFT JOIN leave_requests lr
                ON lr.student_id = sp.id
                AND lr.timetable_id = s.timetable_id
                AND lr.lecture_date = s.lecture_date

            WHERE sp.id = ?

            ORDER BY
                COALESCE(
                    s.closed_at,
                    s.started_at
                ) DESC,
                s.id DESC
            """,
            (user["id"],),
        ).fetchall()

    finally:
        db.close()

    history = []

    subject_data = {}

    present = 0
    absent = 0
    leave = 0

    for row in rows:

        # ----------------------------------------------------
        # Determine final display status
        # ----------------------------------------------------

        if row["record_status"] == "present":

            status = "present"

        elif row["leave_status"] == "Approved Leave":

            # Approved leave counts as PRESENT for percentage.
            status = "leave"

        else:

            status = "absent"

        # ----------------------------------------------------
        # History
        # ----------------------------------------------------

        history.append(
            {
                "session_id": row["session_id"],
                "date": (
                    row["lecture_date"]
                    or row["closed_at"]
                    or row["started_at"]
                ),
                "subject_name": row["subject_name"],
                "subject_code": row["subject_code"],
                "status": status,
                "leave_status": row["leave_status"],
                "method": row["method"] or "-",
            }
        )

        # ----------------------------------------------------
        # Subject-wise data
        # ----------------------------------------------------

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

            present += 1

        elif status == "leave":

            # Approved leave counts as present.
            item["leave"] += 1
            item["present"] += 1

            leave += 1
            present += 1

        else:

            item["absent"] += 1

            absent += 1

    # --------------------------------------------------------
    # Subject percentage
    # --------------------------------------------------------

    subjects = []

    for item in subject_data.values():

        item.update(
            _percent_info(
                item["present"],
                item["absent"]
            )
        )

        subjects.append(item)

    subjects.sort(
        key=lambda x: x["subject_name"].lower()
    )

    # --------------------------------------------------------
    # Overall percentage
    # --------------------------------------------------------

    overall = {
        "total": len(rows),
        "present": present,
        "absent": absent,
        "leave": leave,
    }

    overall.update(
        _percent_info(
            present,
            absent
        )
    )

    return {
        "overall": overall,
        "subjects": subjects,
        "history": history,
    }


# ============================================================
# MARK ATTENDANCE
# ============================================================

@router.post("/api/student/attendance/mark")
def mark_attendance(
    request: Request,
    data: AttendanceMarkRequest
):

    user = require_student(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Student login required."
        )

    db = get_connection()

    try:
        return _mark_attendance(
            db,
            user,
            data
        )

    finally:
        db.close()


def _mark_attendance(
    db,
    user,
    data: AttendanceMarkRequest
):

    token = data.token.strip()

    if not token:

        raise HTTPException(
            status_code=400,
            detail="Please enter the QR token."
        )

    # --------------------------------------------------------
    # Validate student location coordinates
    # --------------------------------------------------------

    if not (
        -90 <= data.latitude <= 90
        and
        -180 <= data.longitude <= 180
    ):

        raise HTTPException(
            status_code=400,
            detail="Invalid location coordinates."
        )

    # --------------------------------------------------------
    # Get student profile
    # --------------------------------------------------------

    student = db.execute(
        """
        SELECT
            id,
            division_id,
            roll_number
        FROM student_profiles
        WHERE id = ?
          AND is_active = 1
        """,
        (user["id"],),
    ).fetchone()

    if not student:

        raise HTTPException(
            status_code=404,
            detail="Student profile not found."
        )

    # --------------------------------------------------------
    # Hash submitted QR token
    # --------------------------------------------------------

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    # --------------------------------------------------------
    # Find QR token and attendance session
    # --------------------------------------------------------

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
            detail="Invalid QR code."
        )

    # --------------------------------------------------------
    # Session must still be active
    # --------------------------------------------------------

    if token_row["is_active"] != 1:

        raise HTTPException(
            status_code=400,
            detail="This attendance session is closed."
        )

    # --------------------------------------------------------
    # Check token expiry
    # --------------------------------------------------------

    now = datetime.now()

    expires_at = datetime.fromisoformat(
        token_row["expires_at"]
    )

    if now > expires_at:

        raise HTTPException(
            status_code=400,
            detail=(
                "QR code has expired. "
                "Please use the current QR code."
            )
        )

    # --------------------------------------------------------
    # Student must belong to same division
    # --------------------------------------------------------

    if (
        student["division_id"]
        != token_row["division_id"]
    ):

        raise HTTPException(
            status_code=403,
            detail="You are not part of this class."
        )

    # --------------------------------------------------------
    # Get trusted college location
    #
    # IMPORTANT:
    # We DO NOT trust faculty/session coordinates.
    # Admin configured the trusted college location.
    # --------------------------------------------------------

    college = db.execute(
        """
        SELECT
            latitude,
            longitude,
            radius_meters
        FROM college_settings
        WHERE id = 1
        """
    ).fetchone()

    if not college:

        raise HTTPException(
            status_code=500,
            detail=(
                "College attendance location "
                "has not been configured by admin."
            )
        )

    # --------------------------------------------------------
    # Calculate distance from trusted college location
    # --------------------------------------------------------

    distance = haversine_distance(
        college["latitude"],
        college["longitude"],
        data.latitude,
        data.longitude,
    )

    radius = college["radius_meters"] or 100

    if distance > radius:

        raise HTTPException(
            status_code=403,
            detail=(
                "You are outside the allowed attendance area. "
                f"Distance: {round(distance)} m, "
                f"allowed: {round(radius)} m."
            ),
        )

    # --------------------------------------------------------
    # Duplicate attendance prevention
    # --------------------------------------------------------

    existing = db.execute(
        """
        SELECT id
        FROM attendance_records
        WHERE session_id = ?
          AND student_id = ?
        """,
        (
            token_row["session_id"],
            student["id"],
        ),
    ).fetchone()

    if existing:

        raise HTTPException(
            status_code=400,
            detail="Attendance already marked for this session."
        )

    # --------------------------------------------------------
    # Mark present
    # --------------------------------------------------------

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
            VALUES
            (
                ?,
                ?,
                'present',
                'qr',
                ?,
                NULL,
                ?,
                ?,
                ?
            )
            """,
            (
                token_row["session_id"],
                student["id"],
                now.isoformat(
                    timespec="seconds"
                ),
                data.latitude,
                data.longitude,
                distance,
            ),
        )

        db.commit()

    except sqlite3.IntegrityError:

        raise HTTPException(
            status_code=400,
            detail=(
                "Attendance already marked "
                "for this session."
            )
        )

    return {
        "success": True,
        "message": "Attendance marked successfully!",
        "subject": token_row["subject_name"],
        "subject_code": token_row["subject_code"],
        "distance_m": round(distance, 1),
    }


# ============================================================
# ATTENDANCE PAGE
# ============================================================

@router.get(
    "/student/attendance",
    response_class=HTMLResponse
)
def student_attendance_page(request: Request):

    user = require_student(request)

    if not user:

        return RedirectResponse(
            "/student/login",
            status_code=303
        )

    return templates.TemplateResponse(
        request=request,
        name="student_attendance.html",
        context={
            "current_user": user
        },
    )


# ============================================================
# LEAVE REQUESTS
# ============================================================

class LeaveRequest(BaseModel):
    timetable_id: int
    lecture_date: str
    reason: str


@router.get(
    "/student/leave",
    response_class=HTMLResponse
)
def student_leave_page(request: Request):

    user = require_student(request)

    if not user:

        return RedirectResponse(
            "/student/login",
            status_code=303
        )

    return templates.TemplateResponse(
        request=request,
        name="student_leave.html",
        context={
            "current_user": user
        },
    )


# ============================================================
# ELIGIBLE FUTURE LEAVE LECTURES
# ============================================================

@router.get("/api/student/leave/eligible")
def eligible_leave_sessions(request: Request):

    user = require_student(request)

    if not user:

        raise HTTPException(
            status_code=401,
            detail="Student login required."
        )

    db = get_connection()

    try:

        student = db.execute(
            """
            SELECT
                id,
                division_id
            FROM student_profiles
            WHERE id = ?
              AND is_active = 1
            """,
            (user["id"],),
        ).fetchone()

        if not student:

            raise HTTPException(
                status_code=404,
                detail="Student profile not found."
            )

        # ----------------------------------------------------
        # We determine upcoming timetable occurrences.
        #
        # SQLite day_of_week:
        # 0 = Monday
        # 1 = Tuesday
        # ...
        # 6 = Sunday
        #
        # Python weekday() follows the same numbering.
        # ----------------------------------------------------

        today = datetime.now().date()

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

            WHERE
                t.division_id = ?
                AND t.entry_type IN ('LECTURE', 'LAB')

            ORDER BY
                t.day_of_week,
                t.start_time
            """,
            (student["division_id"],),
        ).fetchall()

        eligible = []

        # ----------------------------------------------------
        # Find the next occurrence of each timetable entry.
        #
        # We only show future occurrences.
        # ----------------------------------------------------

        for row in timetable_rows:

            days_ahead = (
                row["day_of_week"]
                - today.weekday()
            ) % 7

            occurrence_date = (
                today
                + timedelta(days=days_ahead)
            )

            # Convert timetable start time into datetime.
            try:

                start_time = datetime.strptime(
                    row["start_time"],
                    "%H:%M"
                ).time()

            except ValueError:

                continue

            occurrence_datetime = datetime.combine(
                occurrence_date,
                start_time
            )

            # If today's lecture has already started,
            # move to next week's occurrence.
            if occurrence_datetime <= datetime.now():

                occurrence_date += timedelta(days=7)

            lecture_date = occurrence_date.isoformat()

            # ------------------------------------------------
            # Check if this occurrence is already closed/past
            # through an attendance session.
            # ------------------------------------------------

            existing_session = db.execute(
                """
                SELECT id
                FROM attendance_sessions
                WHERE timetable_id = ?
                  AND lecture_date = ?
                LIMIT 1
                """,
                (
                    row["timetable_id"],
                    lecture_date,
                ),
            ).fetchone()

            if existing_session:

                continue

            # ------------------------------------------------
            # Check if student already has leave for it.
            # ------------------------------------------------

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

            eligible.append(
                {
                    "timetable_id": row["timetable_id"],
                    "lecture_date": lecture_date,
                    "day_of_week": row["day_of_week"],
                    "start_time": row["start_time"],
                    "end_time": row["end_time"],
                    "entry_type": row["entry_type"],
                    "title": row["title"],
                    "subject_id": row["subject_id"],
                    "subject_name": row["subject_name"],
                    "subject_code": row["subject_code"],
                    "faculty_name": row["faculty_name"],
                }
            )

    finally:

        db.close()

    # Earliest upcoming lectures first.
    eligible.sort(
        key=lambda x: (
            x["lecture_date"],
            x["start_time"]
        )
    )

    return {
        "lectures": eligible
    }


# ============================================================
# SUBMIT FUTURE LEAVE
# ============================================================

@router.post("/api/student/leave")
def submit_leave(
    request: Request,
    data: LeaveRequest
):

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
            detail=(
                "Reason must be 500 characters "
                "or fewer."
            )
        )

    # --------------------------------------------------------
    # Validate lecture date format
    # --------------------------------------------------------

    try:

        lecture_date = datetime.strptime(
            data.lecture_date,
            "%Y-%m-%d"
        ).date()

    except ValueError:

        raise HTTPException(
            status_code=400,
            detail="Invalid lecture date."
        )

    # --------------------------------------------------------
    # Lecture cannot be in the past.
    # --------------------------------------------------------

    if lecture_date < datetime.now().date():

        raise HTTPException(
            status_code=400,
            detail=(
                "Leave can only be requested "
                "for a future lecture."
            )
        )

    db = get_connection()

    try:

        # ----------------------------------------------------
        # Get student
        # ----------------------------------------------------

        student = db.execute(
            """
            SELECT
                id,
                division_id
            FROM student_profiles
            WHERE id = ?
              AND is_active = 1
            """,
            (user["id"],),
        ).fetchone()

        if not student:

            raise HTTPException(
                status_code=404,
                detail="Student profile not found."
            )

        # ----------------------------------------------------
        # Get timetable entry
        # ----------------------------------------------------

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
                detail=(
                    "This timetable lecture "
                    "was not found."
                )
            )

        # ----------------------------------------------------
        # Verify the date actually belongs to this
        # timetable's weekly day.
        # ----------------------------------------------------

        if (
            lecture_date.weekday()
            != timetable["day_of_week"]
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "The selected date does not "
                    "match this timetable lecture."
                )
            )

        # ----------------------------------------------------
        # Build exact lecture start datetime.
        # ----------------------------------------------------

        try:

            start_time = datetime.strptime(
                timetable["start_time"],
                "%H:%M"
            ).time()

        except ValueError:

            raise HTTPException(
                status_code=500,
                detail=(
                    "Invalid timetable start time."
                )
            )

        lecture_datetime = datetime.combine(
            lecture_date,
            start_time
        )

        # ----------------------------------------------------
        # A leave request cannot be submitted once the
        # lecture has started.
        # ----------------------------------------------------

        if lecture_datetime <= datetime.now():

            raise HTTPException(
                status_code=400,
                detail=(
                    "This lecture has already "
                    "started or passed. "
                    "New leave requests are not allowed."
                )
            )

        # ----------------------------------------------------
        # Check whether attendance session has already been
        # created for this lecture occurrence.
        # ----------------------------------------------------

        existing_session = db.execute(
            """
            SELECT
                id,
                is_active
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
                status_code=400,
                detail=(
                    "Attendance for this lecture "
                    "has already started. "
                    "Leave can no longer be requested."
                )
            )

        # ----------------------------------------------------
        # Check existing leave
        # ----------------------------------------------------

        existing_leave = db.execute(
            """
            SELECT
                id,
                status
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
                status_code=400,
                detail=(
                    "Leave has already been "
                    "submitted for this lecture."
                )
            )

        # ----------------------------------------------------
        # Insert leave request
        # ----------------------------------------------------

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
                VALUES
                (
                    ?,
                    ?,
                    ?,
                    ?,
                    'Pending Leave',
                    ?
                )
                """,
                (
                    student["id"],
                    data.timetable_id,
                    lecture_date.isoformat(),
                    reason,
                    datetime.now().isoformat(
                        timespec="seconds"
                    ),
                ),
            )

            db.commit()

        except sqlite3.IntegrityError:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Leave has already been "
                    "submitted for this lecture."
                )
            )

    finally:

        db.close()

    return {
        "success": True,
        "message": (
            "Leave request submitted successfully."
        ),
    }


# ============================================================
# STUDENT LEAVE HISTORY
# ============================================================

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
                lr.start_time DESC,
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


# ============================================================
# STUDENT TIMETABLE
# ============================================================

@router.get(
    "/student/timetable",
    response_class=HTMLResponse
)

def student_timetable(request: Request):

    student = require_student(request)

    if not student:

        return RedirectResponse(
            "/student/login",
            status_code=303
        )

    conn = get_connection()

    try:

        # ----------------------------------------------------
        # Get student's division
        # ----------------------------------------------------

        profile = conn.execute(
            """
            SELECT
                division_id
            FROM student_profiles
            WHERE id = ?
            """,
            (student["id"],),
        ).fetchone()

        if profile is None:

            return RedirectResponse(
                url="/dashboard",
                status_code=303
            )

        # ----------------------------------------------------
        # Get timetable
        # ----------------------------------------------------

        timetable = conn.execute(
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

            WHERE
                t.division_id = ?

                OR t.entry_type IN (
                    'HOD_USE',
                    'OTHER'
                )

            ORDER BY
                t.day_of_week,
                t.start_time
            """,
            (profile["division_id"],),
        ).fetchall()

    finally:

        conn.close()

    return templates.TemplateResponse(
        request=request,
        name="student_timetable.html",
        context={
            "current_user": student,
            "timetable": timetable,
        },
    )

@router.get("/api/timetable")
def get_student_timetable(request: Request):
    user = require_student(request)

    conn = get_connection()
    try:
        student = conn.execute(
            """
            SELECT department_id, semester_id, division_id
            FROM student_profiles
            WHERE id = ?
            """,
            (user["id"],)
        ).fetchone()

        if not student:
            raise HTTPException(
                status_code=404,
                detail="Student profile not found."
            )

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
                f.name AS faculty_name,
                d.name AS division_name
            FROM timetable t
            LEFT JOIN subjects s
                ON t.subject_id = s.id
            LEFT JOIN faculty_profiles f
                ON t.faculty_id = f.id
            LEFT JOIN divisions d
                ON t.division_id = d.id
            WHERE t.division_id = ?
              AND t.day_of_week BETWEEN 0 AND 5
            ORDER BY t.day_of_week, t.start_time
            """,
            (student["division_id"],)
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
                "faculty_name": row["faculty_name"],
                "division_name": row["division_name"],
            })

        return {
            "student_id": user["id"],
            "division_id": student["division_id"],
            "timetable": timetable
        }

    finally:
        conn.close()