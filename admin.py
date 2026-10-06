from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from auth import get_current_user
from database import get_connection


router = APIRouter(prefix="/admin")

templates = Jinja2Templates(directory="templates")


def get_admin_user(request: Request):
    """
    Return the logged-in user only if the user is an admin.
    Otherwise return None.
    """

    user = get_current_user(request)

    if user is None:
        return None

    if user["role"] != "admin":
        return None

    return user


def admin_redirect():
    return RedirectResponse(
        url="/admin/login",
        status_code=303,
    )


@router.get(
    "/dashboard",
    response_class=HTMLResponse,
)
def admin_dashboard(request: Request):

    admin = get_admin_user(request)

    if admin is None:

        user = get_current_user(request)

        if user is not None:
            return RedirectResponse(
                url="/dashboard",
                status_code=303,
            )

        return admin_redirect()

    conn = get_connection()

    try:

        department_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM departments
            """
        ).fetchone()[0]

        semester_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM semesters
            """
        ).fetchone()[0]

        division_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM divisions
            """
        ).fetchone()[0]

        subject_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM subjects
            """
        ).fetchone()[0]

        faculty_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE role = 'faculty'
            """
        ).fetchone()[0]

        student_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE role = 'student'
            """
        ).fetchone()[0]

    finally:
        conn.close()

    return templates.TemplateResponse(
        request=request,
        name="admin_dashboard.html",
        context={
            "current_user": admin,
            "department_count": department_count,
            "semester_count": semester_count,
            "division_count": division_count,
            "subject_count": subject_count,
            "faculty_count": faculty_count,
            "student_count": student_count,
        },
    )


@router.get(
    "/manage",
    response_class=HTMLResponse,
)
def admin_manage_page(request: Request):

    admin = get_admin_user(request)

    if admin is None:
        return admin_redirect()

    conn = get_connection()

    try:

        departments = conn.execute(
            """
            SELECT
                id,
                name,
                code
            FROM departments
            ORDER BY name
            """
        ).fetchall()

        semesters = conn.execute(
            """
            SELECT
                semesters.id,
                semesters.number,
                semesters.department_id,
                departments.name AS department_name,
                departments.code AS department_code
            FROM semesters
            JOIN departments
                ON departments.id = semesters.department_id
            ORDER BY
                departments.name,
                semesters.number
            """
        ).fetchall()

        divisions = conn.execute(
            """
            SELECT
                divisions.id,
                divisions.name,
                divisions.department_id,
                divisions.semester_id,
                departments.code AS department_code,
                semesters.number AS semester_number
            FROM divisions
            JOIN departments
                ON departments.id = divisions.department_id
            JOIN semesters
                ON semesters.id = divisions.semester_id
            ORDER BY
                departments.name,
                semesters.number,
                divisions.name
            """
        ).fetchall()

        subjects = conn.execute(
            """
            SELECT
                subjects.id,
                subjects.name,
                subjects.code,
                subjects.department_id,
                subjects.semester_id,
                departments.code AS department_code,
                semesters.number AS semester_number
            FROM subjects
            JOIN departments
                ON departments.id = subjects.department_id
            JOIN semesters
                ON semesters.id = subjects.semester_id
            ORDER BY
                departments.name,
                semesters.number,
                subjects.code
            """
        ).fetchall()

        faculty = conn.execute(
            """
            SELECT
                users.id,
                users.name,
                users.email,
                faculty_profiles.employee_id,
                departments.name AS department_name,
                departments.code AS department_code
            FROM users
            JOIN faculty_profiles
                ON faculty_profiles.user_id = users.id
            JOIN departments
                ON departments.id = faculty_profiles.department_id
            WHERE users.role = 'faculty'
            ORDER BY users.name
            """
        ).fetchall()

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

            ORDER BY
                timetable.day_of_week,
                timetable.start_time
            """
        ).fetchall()

    finally:
        conn.close()

    return templates.TemplateResponse(
        request=request,
        name="admin_manage.html",
        context={
            "current_user": admin,
            "departments": departments,
            "semesters": semesters,
            "divisions": divisions,
            "subjects": subjects,
            "faculty": faculty,
            "timetable": timetable,
        },
    )


@router.post("/departments/create")
def create_department(
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
):

    admin = get_admin_user(request)

    if admin is None:
        return admin_redirect()

    name = name.strip()
    code = code.strip().upper()

    if not name or not code:
        return RedirectResponse(
            url="/admin/manage",
            status_code=303,
        )

    conn = get_connection()

    try:

        existing = conn.execute(
            """
            SELECT id
            FROM departments
            WHERE name = ?
               OR code = ? COLLATE NOCASE
            """,
            (
                name,
                code,
            ),
        ).fetchone()

        if existing is None:

            conn.execute(
                """
                INSERT INTO departments
                (
                    name,
                    code
                )
                VALUES (?, ?)
                """,
                (
                    name,
                    code,
                ),
            )

            conn.commit()

    finally:
        conn.close()

    return RedirectResponse(
        url="/admin/manage",
        status_code=303,
    )


@router.post("/semesters/create")
def create_semester(
    request: Request,
    department_id: int = Form(...),
    number: int = Form(...),
):

    admin = get_admin_user(request)

    if admin is None:
        return admin_redirect()

    if number < 1 or number > 8:
        return RedirectResponse(
            url="/admin/manage",
            status_code=303,
        )

    conn = get_connection()

    try:

        department = conn.execute(
            """
            SELECT id
            FROM departments
            WHERE id = ?
            """,
            (department_id,),
        ).fetchone()

        if department is None:
            return RedirectResponse(
                url="/admin/manage",
                status_code=303,
            )

        existing = conn.execute(
            """
            SELECT id
            FROM semesters
            WHERE department_id = ?
              AND number = ?
            """,
            (
                department_id,
                number,
            ),
        ).fetchone()

        if existing is None:

            conn.execute(
                """
                INSERT INTO semesters
                (
                    department_id,
                    number
                )
                VALUES (?, ?)
                """,
                (
                    department_id,
                    number,
                ),
            )

            conn.commit()

    finally:
        conn.close()

    return RedirectResponse(
        url="/admin/manage",
        status_code=303,
    )


@router.post("/divisions/create")
def create_division(
    request: Request,
    department_id: int = Form(...),
    semester_id: int = Form(...),
    name: str = Form(...),
):

    admin = get_admin_user(request)

    if admin is None:
        return admin_redirect()

    name = name.strip().upper()

    conn = get_connection()

    try:

        valid_semester = conn.execute(
            """
            SELECT id
            FROM semesters
            WHERE id = ?
              AND department_id = ?
            """,
            (
                semester_id,
                department_id,
            ),
        ).fetchone()

        if valid_semester is None:
            return RedirectResponse(
                url="/admin/manage",
                status_code=303,
            )

        existing = conn.execute(
            """
            SELECT id
            FROM divisions
            WHERE department_id = ?
              AND semester_id = ?
              AND name = ?
            """,
            (
                department_id,
                semester_id,
                name,
            ),
        ).fetchone()

        if existing is None:

            conn.execute(
                """
                INSERT INTO divisions
                (
                    department_id,
                    semester_id,
                    name
                )
                VALUES (?, ?, ?)
                """,
                (
                    department_id,
                    semester_id,
                    name,
                ),
            )

            conn.commit()

    finally:
        conn.close()

    return RedirectResponse(
        url="/admin/manage",
        status_code=303,
    )


@router.post("/subjects/create")
def create_subject(
    request: Request,
    department_id: int = Form(...),
    semester_id: int = Form(...),
    name: str = Form(...),
    code: str = Form(...),
):

    admin = get_admin_user(request)

    if admin is None:
        return admin_redirect()

    name = name.strip()
    code = code.strip().upper()

    conn = get_connection()

    try:

        valid_semester = conn.execute(
            """
            SELECT id
            FROM semesters
            WHERE id = ?
              AND department_id = ?
            """,
            (
                semester_id,
                department_id,
            ),
        ).fetchone()

        if valid_semester is None:
            return RedirectResponse(
                url="/admin/manage",
                status_code=303,
            )

        existing = conn.execute(
            """
            SELECT id
            FROM subjects
            WHERE department_id = ?
              AND semester_id = ?
              AND code = ? COLLATE NOCASE
            """,
            (
                department_id,
                semester_id,
                code,
            ),
        ).fetchone()

        if existing is None:

            conn.execute(
                """
                INSERT INTO subjects
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
                    semester_id,
                    name,
                    code,
                ),
            )

            conn.commit()

    finally:
        conn.close()

    return RedirectResponse(
        url="/admin/manage",
        status_code=303,
    )


@router.post("/assignments/create")
def create_assignment(
    request: Request,
    faculty_user_id: int = Form(...),
    subject_id: int = Form(...),
    division_id: int = Form(...),
):

    admin = get_admin_user(request)

    if admin is None:
        return admin_redirect()

    conn = get_connection()

    try:

        # ---------------------------------------------------------
        # Get faculty department
        # ---------------------------------------------------------

        faculty = conn.execute(
            """
            SELECT
                user_id,
                department_id
            FROM faculty_profiles
            WHERE user_id = ?
            """,
            (faculty_user_id,),
        ).fetchone()

        if faculty is None:
            return RedirectResponse(
                url="/admin/manage",
                status_code=303,
            )

        # ---------------------------------------------------------
        # Get subject department + semester
        # ---------------------------------------------------------

        subject = conn.execute(
            """
            SELECT
                id,
                department_id,
                semester_id
            FROM subjects
            WHERE id = ?
            """,
            (subject_id,),
        ).fetchone()

        if subject is None:
            return RedirectResponse(
                url="/admin/manage",
                status_code=303,
            )

        # ---------------------------------------------------------
        # Get division department + semester
        # ---------------------------------------------------------

        division = conn.execute(
            """
            SELECT
                id,
                department_id,
                semester_id
            FROM divisions
            WHERE id = ?
            """,
            (division_id,),
        ).fetchone()

        if division is None:
            return RedirectResponse(
                url="/admin/manage",
                status_code=303,
            )

        # ---------------------------------------------------------
        # Compatibility check
        # ---------------------------------------------------------

        if faculty["department_id"] != subject["department_id"]:
            return RedirectResponse(
                url="/admin/manage",
                status_code=303,
            )

        if subject["department_id"] != division["department_id"]:
            return RedirectResponse(
                url="/admin/manage",
                status_code=303,
            )

        if subject["semester_id"] != division["semester_id"]:
            return RedirectResponse(
                url="/admin/manage",
                status_code=303,
            )

        # ---------------------------------------------------------
        # Prevent duplicate assignment
        # ---------------------------------------------------------

        existing = conn.execute(
            """
            SELECT id
            FROM faculty_assignments
            WHERE faculty_user_id = ?
              AND subject_id = ?
              AND division_id = ?
            """,
            (
                faculty_user_id,
                subject_id,
                division_id,
            ),
        ).fetchone()

        if existing is None:

            conn.execute(
                """
                INSERT INTO faculty_assignments
                (
                    faculty_user_id,
                    subject_id,
                    division_id
                )
                VALUES (?, ?, ?)
                """,
                (
                    faculty_user_id,
                    subject_id,
                    division_id,
                ),
            )

            conn.commit()

    finally:
        conn.close()

    return RedirectResponse(
        url="/admin/manage",
        status_code=303,
    )

@router.post("/timetable/create")
def create_timetable(
    request: Request,
    day_of_week: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    entry_type: str = Form(...),
    division_id: int | None = Form(None),
    subject_id: int | None = Form(None),
    faculty_user_id: int | None = Form(None),
    title: str = Form(""),
):

    admin = get_admin_user(request)

    if admin is None:
        return admin_redirect()

    allowed_types = {
        "LECTURE",
        "LAB",
        "HOD_USE",
        "OTHER",
    }

    if entry_type not in allowed_types:
        return RedirectResponse(
            url="/admin/manage",
            status_code=303,
        )

    if day_of_week < 0 or day_of_week > 6:
        return RedirectResponse(
            url="/admin/manage",
            status_code=303,
        )

    if start_time >= end_time:
        return RedirectResponse(
            url="/admin/manage",
            status_code=303,
        )

    conn = get_connection()

    try:

        # Lecture or Lab must have faculty, subject and class
        if entry_type in {"LECTURE", "LAB"}:

            if not division_id or not subject_id or not faculty_user_id:
                return RedirectResponse(
                    url="/admin/manage",
                    status_code=303,
                )

            assignment = conn.execute(
                """
                SELECT id
                FROM faculty_assignments
                WHERE faculty_user_id = ?
                  AND subject_id = ?
                  AND division_id = ?
                """,
                (
                    faculty_user_id,
                    subject_id,
                    division_id,
                ),
            ).fetchone()

            if assignment is None:
                return RedirectResponse(
                    url="/admin/manage",
                    status_code=303,
                )

        else:
            # HOD/Other doesn't need academic assignment
            division_id = None
            subject_id = None
            faculty_user_id = None

            if not title.strip():
                return RedirectResponse(
                    url="/admin/manage",
                    status_code=303,
                )

        # Prevent same faculty or same division
        # from having overlapping entries.
        overlap = conn.execute(
            """
            SELECT id
            FROM timetable
            WHERE day_of_week = ?
              AND start_time < ?
              AND end_time > ?
              AND (
                    division_id = ?
                    OR faculty_user_id = ?
                  )
            """,
            (
                day_of_week,
                end_time,
                start_time,
                division_id,
                faculty_user_id,
            ),
        ).fetchone()

        if overlap is not None:
            return RedirectResponse(
                url="/admin/manage",
                status_code=303,
            )

        conn.execute(
            """
            INSERT INTO timetable
            (
                day_of_week,
                start_time,
                end_time,
                entry_type,
                division_id,
                subject_id,
                faculty_user_id,
                title
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                day_of_week,
                start_time,
                end_time,
                entry_type,
                division_id,
                subject_id,
                faculty_user_id,
                title.strip() or None,
            ),
        )

        conn.commit()

    finally:
        conn.close()

    return RedirectResponse(
        url="/admin/manage",
        status_code=303,
    )


@router.get(
    "/classes",
    response_class=HTMLResponse,
)
def admin_classes(request: Request):

    admin = get_admin_user(request)

    if admin is None:
        return admin_redirect()

    conn = get_connection()

    try:

        classes = conn.execute(
            """
            SELECT
                divisions.id,
                divisions.name AS division_name,
                departments.id AS department_id,
                departments.name AS department_name,
                departments.code AS department_code,
                semesters.id AS semester_id,
                semesters.number AS semester_number,

                (
                    SELECT COUNT(*)
                    FROM student_profiles AS sp
                    WHERE sp.division_id = divisions.id
                ) AS student_count

            FROM divisions

            JOIN departments
                ON departments.id = divisions.department_id

            JOIN semesters
                ON semesters.id = divisions.semester_id

            ORDER BY
                departments.name,
                semesters.number,
                divisions.name
            """
        ).fetchall()

    finally:
        conn.close()

    return templates.TemplateResponse(
        request=request,
        name="admin_classes.html",
        context={
            "current_user": admin,
            "classes": classes,
        },
    )


@router.get(
    "/classes/{division_id}/students",
    response_class=HTMLResponse,
)
def admin_class_students(
    request: Request,
    division_id: int,
):

    admin = get_admin_user(request)

    if admin is None:
        return admin_redirect()

    conn = get_connection()

    try:

        class_info = conn.execute(
            """
            SELECT
                divisions.id,
                divisions.name AS division_name,
                departments.name AS department_name,
                departments.code AS department_code,
                semesters.number AS semester_number
            FROM divisions
            JOIN departments
                ON departments.id = divisions.department_id
            JOIN semesters
                ON semesters.id = divisions.semester_id
            WHERE divisions.id = ?
            """,
            (division_id,),
        ).fetchone()

        if class_info is None:
            return RedirectResponse(
                url="/admin/classes",
                status_code=303,
            )

        students = conn.execute(
            """
            SELECT
                users.id,
                users.name,
                users.email,
                student_profiles.roll_number
            FROM student_profiles
            JOIN users
                ON users.id = student_profiles.user_id
            WHERE student_profiles.division_id = ?
            ORDER BY student_profiles.roll_number
            """,
            (division_id,),
        ).fetchall()

    finally:
        conn.close()

    return templates.TemplateResponse(
        request=request,
        name="admin_students.html",
        context={
            "current_user": admin,
            "class_info": class_info,
            "students": students,
        },
    )


@router.get(
    "/students/{student_user_id}",
    response_class=HTMLResponse,
)
def admin_student_detail(
    request: Request,
    student_user_id: int,
):

    admin = get_admin_user(request)

    if admin is None:
        return admin_redirect()

    conn = get_connection()

    try:

        student = conn.execute(
            """
            SELECT
                users.id,
                users.name,
                users.email,
                student_profiles.roll_number,
                departments.name AS department_name,
                departments.code AS department_code,
                semesters.number AS semester_number,
                divisions.name AS division_name
            FROM student_profiles

            JOIN users
                ON users.id = student_profiles.user_id

            JOIN departments
                ON departments.id = student_profiles.department_id

            JOIN semesters
                ON semesters.id = student_profiles.semester_id

            JOIN divisions
                ON divisions.id = student_profiles.division_id

            WHERE student_profiles.user_id = ?
            """,
            (student_user_id,),
        ).fetchone()

        if student is None:
            return RedirectResponse(
                url="/admin/classes",
                status_code=303,
            )

        attendance = conn.execute(
            """
            SELECT
                attendance.marked_at,
                attendance.status,
                subjects.name AS subject_name,
                subjects.code AS subject_code
            FROM attendance

            JOIN attendance_sessions
                ON attendance_sessions.id = attendance.session_id

            JOIN subjects
                ON subjects.id = attendance_sessions.subject_id

            WHERE attendance.student_user_id = ?

            ORDER BY attendance.marked_at DESC
            """,
            (student_user_id,),
        ).fetchall()

        leaves = conn.execute(
            """
            SELECT
                leave_requests.reason,
                leave_requests.status,
                leave_requests.submitted_at,
                leave_requests.reviewed_at,
                subjects.name AS subject_name,
                subjects.code AS subject_code
            FROM leave_requests

            JOIN attendance_sessions
                ON attendance_sessions.id = leave_requests.session_id

            JOIN subjects
                ON subjects.id = attendance_sessions.subject_id

            WHERE leave_requests.student_user_id = ?

            ORDER BY leave_requests.submitted_at DESC
            """,
            (student_user_id,),
        ).fetchall()

    finally:
        conn.close()

    return templates.TemplateResponse(
        request=request,
        name="admin_student_detail.html",
        context={
            "current_user": admin,
            "student": student,
            "attendance": attendance,
            "leaves": leaves,
        },
    )


@router.get(
    "/faculty",
    response_class=HTMLResponse,
)
def admin_faculty(
    request: Request,
):

    admin = get_admin_user(request)

    if admin is None:
        return admin_redirect()

    conn = get_connection()

    try:

        faculty = conn.execute(
            """
            SELECT
                users.id,
                users.name,
                users.email,
                faculty_profiles.employee_id,
                departments.name AS department_name,
                departments.code AS department_code,

                (
                    SELECT COUNT(*)
                    FROM faculty_assignments AS fa
                    WHERE fa.faculty_user_id = users.id
                ) AS assignment_count

            FROM users

            JOIN faculty_profiles
                ON faculty_profiles.user_id = users.id

            JOIN departments
                ON departments.id = faculty_profiles.department_id

            WHERE users.role = 'faculty'

            ORDER BY users.name
            """
        ).fetchall()

    finally:
        conn.close()

    return templates.TemplateResponse(
        request=request,
        name="admin_manage.html",
        context={
            "current_user": admin,
            "departments": [],
            "semesters": [],
            "divisions": [],
            "subjects": [],
            "faculty": faculty,
        },
    )

# ============================================================
# COLLEGE ATTENDANCE LOCATION
# ============================================================

@router.post("/api/college-location")
async def set_college_location(request: Request):

    user = get_current_user(request)

    if not user or user["role"] != "admin":
        return JSONResponse(
            {"error": "Admin login required."},
            status_code=401
        )

    try:
        data = await request.json()

        latitude = float(data.get("latitude"))
        longitude = float(data.get("longitude"))
        radius_meters = float(
            data.get("radius_meters", 100)
        )

    except (TypeError, ValueError):
        return JSONResponse(
            {"error": "Invalid location or radius."},
            status_code=400
        )

    if not (-90 <= latitude <= 90):
        return JSONResponse(
            {"error": "Invalid latitude."},
            status_code=400
        )

    if not (-180 <= longitude <= 180):
        return JSONResponse(
            {"error": "Invalid longitude."},
            status_code=400
        )

    if radius_meters <= 0:
        return JSONResponse(
            {"error": "Radius must be greater than 0."},
            status_code=400
        )

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO college_settings
        (
            id,
            latitude,
            longitude,
            radius_meters
        )
        VALUES (1, ?, ?, ?)
        ON CONFLICT(id)
        DO UPDATE SET
            latitude = excluded.latitude,
            longitude = excluded.longitude,
            radius_meters = excluded.radius_meters
        """,
        (
            latitude,
            longitude,
            radius_meters
        )
    )

    conn.commit()
    conn.close()

    return JSONResponse(
        {
            "success": True,
            "message": "College attendance location saved."
        }
    )