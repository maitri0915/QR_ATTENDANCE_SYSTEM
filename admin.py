from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from auth import get_current_user
from database import get_connection


router = APIRouter(prefix="/admin")

templates = Jinja2Templates(directory="templates")


# ============================================================
# ADMIN AUTH
# ============================================================

def get_admin_user(request: Request):
    """
    Return the logged-in account only if it is an admin.
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


# ============================================================
# ADMIN DASHBOARD
# ============================================================

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
            FROM faculty_profiles
            WHERE is_active = 1
            """
        ).fetchone()[0]

        student_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM student_profiles
            WHERE is_active = 1
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


# ============================================================
# ADMIN MANAGE PAGE
# ============================================================

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
                faculty_profiles.id,
                faculty_profiles.name,
                faculty_profiles.email,
                faculty_profiles.employee_id,

                departments.name AS department_name,
                departments.code AS department_code

            FROM faculty_profiles

            JOIN departments
                ON departments.id = faculty_profiles.department_id

            WHERE faculty_profiles.is_active = 1

            ORDER BY faculty_profiles.name
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

            ORDER BY
                timetable.day_of_week,
                timetable.start_time
            """
        ).fetchall()

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
            "college_location": college_location,
        },
    )


# ============================================================
# CREATE DEPARTMENT
# ============================================================

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


# ============================================================
# CREATE SEMESTER
# ============================================================

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


# ============================================================
# CREATE DIVISION
# ============================================================

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

    if not name:
        return RedirectResponse(
            url="/admin/manage",
            status_code=303,
        )

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


# ============================================================
# CREATE SUBJECT
# ============================================================

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

    if not name or not code:
        return RedirectResponse(
            url="/admin/manage",
            status_code=303,
        )

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


# ============================================================
# CREATE FACULTY ASSIGNMENT
# ============================================================

@router.post("/assignments/create")
def create_assignment(
    request: Request,
    faculty_id: int = Form(...),
    subject_id: int = Form(...),
    division_id: int = Form(...),
):

    admin = get_admin_user(request)

    if admin is None:
        return admin_redirect()

    conn = get_connection()

    try:

        faculty = conn.execute(
            """
            SELECT
                id,
                department_id
            FROM faculty_profiles
            WHERE id = ?
              AND is_active = 1
            """,
            (faculty_id,),
        ).fetchone()

        if faculty is None:
            return RedirectResponse(
                url="/admin/manage",
                status_code=303,
            )

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

        # --------------------------------------------------------
        # Faculty, subject and division must belong together
        # --------------------------------------------------------

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

        existing = conn.execute(
            """
            SELECT id
            FROM faculty_assignments
            WHERE faculty_id = ?
              AND subject_id = ?
              AND division_id = ?
            """,
            (
                faculty_id,
                subject_id,
                division_id,
            ),
        ).fetchone()

        if existing is None:

            conn.execute(
                """
                INSERT INTO faculty_assignments
                (
                    faculty_id,
                    subject_id,
                    division_id
                )
                VALUES (?, ?, ?)
                """,
                (
                    faculty_id,
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


# ============================================================
# CREATE TIMETABLE ENTRY
# ============================================================

@router.post("/timetable/create")
def create_timetable(
    request: Request,
    day_of_week: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    entry_type: str = Form(...),
    division_id: int | None = Form(None),
    subject_id: int | None = Form(None),
    faculty_id: int | None = Form(None),
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

    if not 0 <= day_of_week <= 5:
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

        # --------------------------------------------------------
        # Lecture / Lab
        # --------------------------------------------------------

        if entry_type in {"LECTURE", "LAB"}:

            if (
                division_id is None
                or subject_id is None
                or faculty_id is None
            ):
                return RedirectResponse(
                    url="/admin/manage",
                    status_code=303,
                )

            assignment = conn.execute(
                """
                SELECT id
                FROM faculty_assignments
                WHERE faculty_id = ?
                  AND subject_id = ?
                  AND division_id = ?
                """,
                (
                    faculty_id,
                    subject_id,
                    division_id,
                ),
            ).fetchone()

            if assignment is None:
                return RedirectResponse(
                    url="/admin/manage",
                    status_code=303,
                )

            # Make sure subject and division belong together.
            valid_subject = conn.execute(
                """
                SELECT id
                FROM subjects
                WHERE id = ?
                  AND semester_id = (
                      SELECT semester_id
                      FROM divisions
                      WHERE id = ?
                  )
                """,
                (
                    subject_id,
                    division_id,
                ),
            ).fetchone()

            if valid_subject is None:
                return RedirectResponse(
                    url="/admin/manage",
                    status_code=303,
                )

        # --------------------------------------------------------
        # HOD / Other
        # --------------------------------------------------------

        else:

            division_id = None
            subject_id = None
            faculty_id = None

            if not title.strip():
                return RedirectResponse(
                    url="/admin/manage",
                    status_code=303,
                )

        # --------------------------------------------------------
        # Prevent timetable overlap
        # --------------------------------------------------------

        overlap = conn.execute(
            """
            SELECT id
            FROM timetable

            WHERE day_of_week = ?

              AND start_time < ?
              AND end_time > ?

              AND (
                    division_id = ?
                    OR faculty_id = ?
                  )
            """,
            (
                day_of_week,
                end_time,
                start_time,
                division_id,
                faculty_id,
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
                faculty_id,
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
                faculty_id,
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


# ============================================================
# ADMIN CLASSES
# ============================================================

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
                    FROM student_profiles sp
                    WHERE sp.division_id = divisions.id
                      AND sp.is_active = 1
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


# ============================================================
# CLASS STUDENTS
# ============================================================

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
                student_profiles.id,
                student_profiles.name,
                student_profiles.email,
                student_profiles.roll_number

            FROM student_profiles

            WHERE student_profiles.division_id = ?
              AND student_profiles.is_active = 1

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


# ============================================================
# STUDENT DETAIL
# ============================================================

@router.get(
    "/students/{student_id}",
    response_class=HTMLResponse,
)
def admin_student_detail(
    request: Request,
    student_id: int,
):

    admin = get_admin_user(request)

    if admin is None:
        return admin_redirect()

    conn = get_connection()

    try:

        student = conn.execute(
            """
            SELECT
                sp.id,
                sp.name,
                sp.email,
                sp.roll_number,

                departments.name AS department_name,
                departments.code AS department_code,

                semesters.number AS semester_number,

                divisions.name AS division_name

            FROM student_profiles sp

            JOIN departments
                ON departments.id = sp.department_id

            JOIN semesters
                ON semesters.id = sp.semester_id

            JOIN divisions
                ON divisions.id = sp.division_id

            WHERE sp.id = ?
            """,
            (student_id,),
        ).fetchone()

        if student is None:
            return RedirectResponse(
                url="/admin/classes",
                status_code=303,
            )

        attendance = conn.execute(
            """
            SELECT
                ar.marked_at,
                ar.status,
                ar.method,

                s.name AS subject_name,
                s.code AS subject_code,

                a.lecture_date,
                t.start_time,
                t.end_time

            FROM attendance_records ar

            JOIN attendance_sessions a
                ON a.id = ar.session_id

            JOIN subjects s
                ON s.id = a.subject_id

            LEFT JOIN timetable t
                ON t.id = a.timetable_id

            WHERE ar.student_id = ?

            ORDER BY
                a.lecture_date DESC,
                ar.marked_at DESC
            """,
            (student_id,),
        ).fetchall()

        leaves = conn.execute(
            """
            SELECT
                lr.id,
                lr.reason,
                lr.status,
                lr.submitted_at,
                lr.reviewed_at,
                lr.lecture_date,

                s.name AS subject_name,
                s.code AS subject_code,

                t.start_time,
                t.end_time,

                d.name AS division_name,

                fp.name AS reviewed_by_name

            FROM leave_requests lr

            JOIN timetable t
                ON t.id = lr.timetable_id

            JOIN subjects s
                ON s.id = t.subject_id

            JOIN divisions d
                ON d.id = t.division_id

            LEFT JOIN faculty_profiles fp
                ON fp.id = lr.reviewed_by

            WHERE lr.student_id = ?

            ORDER BY
                lr.lecture_date DESC,
                lr.submitted_at DESC
            """,
            (student_id,),
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


# ============================================================
# FACULTY LIST
# ============================================================

@router.get(
    "/faculty",
    response_class=HTMLResponse,
)
def admin_faculty(request: Request):

    admin = get_admin_user(request)

    if admin is None:
        return admin_redirect()

    conn = get_connection()

    try:

        faculty = conn.execute(
            """
            SELECT
                fp.id,
                fp.name,
                fp.email,
                fp.employee_id,

                d.name AS department_name,
                d.code AS department_code,

                (
                    SELECT COUNT(*)
                    FROM faculty_assignments fa
                    WHERE fa.faculty_id = fp.id
                ) AS assignment_count

            FROM faculty_profiles fp

            JOIN departments d
                ON d.id = fp.department_id

            WHERE fp.is_active = 1

            ORDER BY fp.name
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
            "timetable": [],
            "college_location": None,
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
            {
                "error":
                    "Admin login required."
            },
            status_code=401,
        )

    try:

        data = await request.json()

        latitude = float(
            data.get("latitude")
        )

        longitude = float(
            data.get("longitude")
        )

        radius_meters = float(
            data.get(
                "radius_meters",
                100,
            )
        )

    except (TypeError, ValueError):

        return JSONResponse(
            {
                "error":
                    "Invalid location or radius."
            },
            status_code=400,
        )

    if not -90 <= latitude <= 90:

        return JSONResponse(
            {
                "error":
                    "Invalid latitude."
            },
            status_code=400,
        )

    if not -180 <= longitude <= 180:

        return JSONResponse(
            {
                "error":
                    "Invalid longitude."
            },
            status_code=400,
        )

    if radius_meters <= 0:

        return JSONResponse(
            {
                "error":
                    "Radius must be greater than 0."
            },
            status_code=400,
        )

    conn = get_connection()

    try:

        conn.execute(
            """
            INSERT INTO college_settings
            (
                id,
                latitude,
                longitude,
                radius_meters
            )

            VALUES (
                1,
                ?,
                ?,
                ?
            )

            ON CONFLICT(id)
            DO UPDATE SET

                latitude =
                    excluded.latitude,

                longitude =
                    excluded.longitude,

                radius_meters =
                    excluded.radius_meters
            """,
            (
                latitude,
                longitude,
                radius_meters,
            ),
        )

        conn.commit()

    finally:
        conn.close()

    return JSONResponse(
        {
            "success": True,
            "message":
                "College attendance location saved.",
        }
    )