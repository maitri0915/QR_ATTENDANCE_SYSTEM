
from datetime import date, datetime, time
import sqlite3

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from templating import templates

from auth import get_current_user
from database import get_connection


router = APIRouter(prefix="/admin")

VALID_ENTRY_TYPES = {"LECTURE", "LAB", "OTHER", "HOD_USE"}
VALID_DAYS = range(6)  # Monday to Saturday; Sunday is not scheduled.


# ---------------------------------------------------------
# AUTHENTICATION AND HELPERS
# ---------------------------------------------------------

def get_admin_user(request: Request):
    """Return the logged-in admin, or None if access is not allowed."""
    user = get_current_user(request)

    if not user or user.get("role") != "admin":
        return None

    try:
        with get_connection() as conn:
            admin = conn.execute(
                """
                SELECT id, name, email, is_active
                FROM admins
                WHERE id = ?
                """,
                (user["id"],),
            ).fetchone()

        if not admin or admin["is_active"] != 1:
            request.session.clear()
            return None

        return dict(admin)
    except (sqlite3.Error, KeyError, TypeError, ValueError):
        return None


def admin_redirect():
    return RedirectResponse("/admin/login", status_code=303)


def admin_error(message: str, status_code: int = 400):
    return HTMLResponse(
        f"<h3>{message}</h3><p><a href='/admin/manage'>Back to Admin Management</a></p>",
        status_code=status_code,
    )


def parse_time(value: str):
    try:
        return time.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None


def get_form_value(value):
    return value.strip() if isinstance(value, str) else ""


def valid_positive_id(value):
    try:
        result = int(value)
        return result if result > 0 else None
    except (ValueError, TypeError):
        return None


def ensure_admin(request: Request):
    return get_admin_user(request)


def timetable_overlap(conn, day_of_week, start_time, end_time,
                      division_id=None, faculty_id=None, exclude_id=None):
    """
    Return a conflict message if the class/division or faculty member
    already has an overlapping timetable entry on the same day.
    """
    conditions = ["day_of_week = ?"]
    params = [day_of_week]

    if exclude_id is not None:
        conditions.append("id != ?")
        params.append(exclude_id)

    conditions.append(
        """
        NOT (end_time <= ? OR start_time >= ?)
        """
    )
    params.extend([start_time, end_time])

    if division_id is not None:
        query = f"""
            SELECT id
            FROM timetable
            WHERE {' AND '.join(conditions)}
              AND division_id = ?
              AND division_id IS NOT NULL
            LIMIT 1
        """
        if conn.execute(query, (*params, division_id)).fetchone():
            return "This class/division already has a timetable entry during that time."

    if faculty_id is not None:
        query = f"""
            SELECT id
            FROM timetable
            WHERE {' AND '.join(conditions)}
              AND faculty_id = ?
              AND faculty_id IS NOT NULL
            LIMIT 1
        """
        if conn.execute(query, (*params, faculty_id)).fetchone():
            return "This faculty member already has a timetable entry during that time."

    return None


# ---------------------------------------------------------
# ADMIN DASHBOARD
# ---------------------------------------------------------

@router.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    admin = ensure_admin(request)
    if not admin:
        return admin_redirect()

    try:
        with get_connection() as conn:
            campus_configured = conn.execute(
                "SELECT 1 FROM college_settings WHERE id = 1"
            ).fetchone() is not None

            stats = {
                "departments": conn.execute(
                    "SELECT COUNT(*) FROM departments"
                ).fetchone()[0],
                "semesters": conn.execute(
                    "SELECT COUNT(*) FROM semesters"
                ).fetchone()[0],
                "divisions": conn.execute(
                    "SELECT COUNT(*) FROM divisions"
                ).fetchone()[0],
                "subjects": conn.execute(
                    "SELECT COUNT(*) FROM subjects"
                ).fetchone()[0],
                "faculty": conn.execute(
                    "SELECT COUNT(*) FROM faculty_profiles WHERE is_active = 1"
                ).fetchone()[0],
                "students": conn.execute(
                    "SELECT COUNT(*) FROM student_profiles WHERE is_active = 1"
                ).fetchone()[0],
            }

        return templates.TemplateResponse(
            "admin_dashboard.html",
            {"request": request, "user": admin,"current_user": admin , "stats": stats, "campus_configured": campus_configured, **stats},
        )
    except sqlite3.Error:
        return admin_error("Unable to load the admin dashboard.", 500)


# ---------------------------------------------------------
# ADMIN MANAGEMENT PAGE
# ---------------------------------------------------------

@router.get("/manage", response_class=HTMLResponse)
def admin_manage(request: Request):
    admin = ensure_admin(request)
    if not admin:
        return admin_redirect()

    try:
        with get_connection() as conn:
            departments = conn.execute(
                "SELECT * FROM departments ORDER BY name"
            ).fetchall()

            semesters = conn.execute(
                """
                SELECT s.*, d.name AS department_name, d.code AS department_code
                FROM semesters s
                JOIN departments d ON d.id = s.department_id
                ORDER BY d.name, s.number
                """
            ).fetchall()

            divisions = conn.execute(
                """
                SELECT v.*, d.name AS department_name,
                       s.number AS semester_number
                FROM divisions v
                JOIN departments d ON d.id = v.department_id
                JOIN semesters s ON s.id = v.semester_id
                ORDER BY d.name, s.number, v.name
                """
            ).fetchall()

            subjects = conn.execute(
                """
                SELECT sub.*, d.name AS department_name,
                       s.number AS semester_number
                FROM subjects sub
                JOIN departments d ON d.id = sub.department_id
                JOIN semesters s ON s.id = sub.semester_id
                ORDER BY d.name, s.number, sub.name
                """
            ).fetchall()

            faculty = conn.execute(
                """
                SELECT id, name, email, employee_id, department_id
                FROM faculty_profiles
                WHERE is_active = 1
                ORDER BY name
                """
            ).fetchall()

            assignments = conn.execute(
                """
                SELECT fa.*,
                       f.name AS faculty_name,
                       sub.name AS subject_name,
                       v.name AS division_name
                FROM faculty_assignments fa
                JOIN faculty_profiles f ON f.id = fa.faculty_id
                JOIN subjects sub ON sub.id = fa.subject_id
                JOIN divisions v ON v.id = fa.division_id
                ORDER BY f.name, sub.name
                """
            ).fetchall()

            timetable = conn.execute(
                """
                SELECT t.*,
                       v.name AS division_name,
                       sub.name AS subject_name,
                       sub.code AS subject_code,
                       f.name AS faculty_name,
                       d.name AS department_name,
                       s.number AS semester_number
                FROM timetable t
                LEFT JOIN divisions v ON v.id = t.division_id
                LEFT JOIN subjects sub ON sub.id = t.subject_id
                LEFT JOIN faculty_profiles f ON f.id = t.faculty_id
                LEFT JOIN divisions dv ON dv.id = t.division_id
                LEFT JOIN departments d ON d.id = dv.department_id
                LEFT JOIN semesters s ON s.id = dv.semester_id
                ORDER BY t.day_of_week, t.start_time
                """
            ).fetchall()

            settings = conn.execute(
                "SELECT * FROM college_settings WHERE id = 1"
            ).fetchone()

        return templates.TemplateResponse(
            "admin_manage.html",
            {
                "request": request,
                "user": admin,
                "current_user": admin,
                "departments": departments,
                "semesters": semesters,
                "divisions": divisions,
                "subjects": subjects,
                "faculty": faculty,
                "assignments": assignments,
                "timetable": timetable,
                "settings": settings,
                "college_settings": settings,
            },
        )
    except sqlite3.Error:
        return admin_error("Unable to load admin management data.", 500)


# ---------------------------------------------------------
# DEPARTMENTS
# ---------------------------------------------------------

@router.post("/departments/create")
def create_department(
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
):
    if not ensure_admin(request):
        return admin_redirect()

    name = get_form_value(name)
    code = get_form_value(code).upper()

    if not name or not code:
        return admin_error("Department name and code are required.")

    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO departments (name, code) VALUES (?, ?)",
                (name, code),
            )
            conn.commit()
        return RedirectResponse("/admin/manage", status_code=303)
    except sqlite3.IntegrityError:
        return admin_error("A department with that name or code already exists.")
    except sqlite3.Error:
        return admin_error("Unable to create the department.", 500)


# ---------------------------------------------------------
# SEMESTERS
# ---------------------------------------------------------

@router.post("/semesters/create")
def create_semester(
    request: Request,
    department_id: int = Form(...),
    number: int = Form(...),
):
    if not ensure_admin(request):
        return admin_redirect()

    if number < 1 or number > 8:
        return admin_error("Semester number must be between 1 and 8.")

    try:
        with get_connection() as conn:
            department = conn.execute(
                "SELECT id FROM departments WHERE id = ?",
                (department_id,),
            ).fetchone()

            if not department:
                return admin_error("Please select a valid department.")

            conn.execute(
                "INSERT INTO semesters (department_id, number) VALUES (?, ?)",
                (department_id, number),
            )
            conn.commit()

        return RedirectResponse("/admin/manage", status_code=303)
    except sqlite3.IntegrityError:
        return admin_error("That semester already exists for this department.")
    except sqlite3.Error:
        return admin_error("Unable to create the semester.", 500)


# ---------------------------------------------------------
# DIVISIONS / CLASSES
# ---------------------------------------------------------

@router.post("/divisions/create")
def create_division(
    request: Request,
    department_id: int = Form(...),
    semester_id: int = Form(...),
    name: str = Form(...),
):
    if not ensure_admin(request):
        return admin_redirect()

    name = get_form_value(name).upper()

    if not name:
        return admin_error("Division name is required.")

    try:
        with get_connection() as conn:
            semester = conn.execute(
                """
                SELECT id FROM semesters
                WHERE id = ? AND department_id = ?
                """,
                (semester_id, department_id),
            ).fetchone()

            if not semester:
                return admin_error(
                    "The selected semester does not belong to that department."
                )

            conn.execute(
                """
                INSERT INTO divisions (department_id, semester_id, name)
                VALUES (?, ?, ?)
                """,
                (department_id, semester_id, name),
            )
            conn.commit()

        return RedirectResponse("/admin/manage", status_code=303)
    except sqlite3.IntegrityError:
        return admin_error("That division already exists.")
    except sqlite3.Error:
        return admin_error("Unable to create the division.", 500)


# ---------------------------------------------------------
# SUBJECTS
# ---------------------------------------------------------

@router.post("/subjects/create")
def create_subject(
    request: Request,
    department_id: int = Form(...),
    semester_id: int = Form(...),
    name: str = Form(...),
    code: str = Form(...),
):
    if not ensure_admin(request):
        return admin_redirect()

    name = get_form_value(name)
    code = get_form_value(code).upper()

    if not name or not code:
        return admin_error("Subject name and code are required.")

    try:
        with get_connection() as conn:
            semester = conn.execute(
                """
                SELECT id FROM semesters
                WHERE id = ? AND department_id = ?
                """,
                (semester_id, department_id),
            ).fetchone()

            if not semester:
                return admin_error(
                    "The selected semester does not belong to that department."
                )

            conn.execute(
                """
                INSERT INTO subjects (department_id, semester_id, name, code)
                VALUES (?, ?, ?, ?)
                """,
                (department_id, semester_id, name, code),
            )
            conn.commit()

        return RedirectResponse("/admin/manage", status_code=303)
    except sqlite3.IntegrityError:
        return admin_error("That subject name or code already exists.")
    except sqlite3.Error:
        return admin_error("Unable to create the subject.", 500)


# ---------------------------------------------------------
# FACULTY ASSIGNMENTS
# ---------------------------------------------------------
# This endpoint remains for compatibility with the existing
# management page. It is no longer a required step before
# creating a timetable entry.

@router.post("/assignments/create")
def create_assignment(
    request: Request,
    faculty_id: int = Form(...),
    subject_id: int = Form(...),
    division_id: int = Form(...),
):
    if not ensure_admin(request):
        return admin_redirect()

    try:
        with get_connection() as conn:
            faculty = conn.execute(
                """
                SELECT id, department_id
                FROM faculty_profiles
                WHERE id = ? AND is_active = 1
                """,
                (faculty_id,),
            ).fetchone()

            subject = conn.execute(
                """
                SELECT id, department_id, semester_id
                FROM subjects WHERE id = ?
                """,
                (subject_id,),
            ).fetchone()

            division = conn.execute(
                """
                SELECT id, department_id, semester_id
                FROM divisions WHERE id = ?
                """,
                (division_id,),
            ).fetchone()

            if not faculty or not subject or not division:
                return admin_error(
                    "Select a valid active faculty member, subject, and division."
                )

            if (
                faculty["department_id"] != subject["department_id"]
                or subject["department_id"] != division["department_id"]
                or subject["semester_id"] != division["semester_id"]
            ):
                return admin_error(
                    "Faculty, subject, and division must belong to compatible departments and semesters."
                )

            conn.execute(
                """
                INSERT OR IGNORE INTO faculty_assignments
                    (faculty_id, subject_id, division_id)
                VALUES (?, ?, ?)
                """,
                (faculty_id, subject_id, division_id),
            )
            conn.commit()

        return RedirectResponse("/admin/manage", status_code=303)
    except sqlite3.Error:
        return admin_error("Unable to create the faculty assignment.", 500)


# ---------------------------------------------------------
# TIMETABLE
# ---------------------------------------------------------
# Main workflow:
# Select a class/division, subject, faculty member, day and time.
# A valid lecture/lab entry automatically creates its assignment.

@router.post("/timetable/create")
def create_timetable(
    request: Request,
    day_of_week: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    entry_type: str = Form("LECTURE"),
    division_id: str = Form(""),
    subject_id: str = Form(""),
    faculty_id: str = Form(""),
    title: str = Form(""),
):
    if not ensure_admin(request):
        return admin_redirect()

    entry_type = get_form_value(entry_type).upper()
    title = get_form_value(title)

    if entry_type not in VALID_ENTRY_TYPES:
        return admin_error("Invalid timetable entry type.")

    if day_of_week not in VALID_DAYS:
        return admin_error("Select a valid day from Monday to Saturday.")

    start = parse_time(start_time)
    end = parse_time(end_time)

    if not start or not end:
        return admin_error("Enter valid start and end times.")

    start_value = start.strftime("%H:%M:%S")
    end_value = end.strftime("%H:%M:%S")

    if start >= end:
        return admin_error("End time must be later than start time.")

    selected_division = valid_positive_id(division_id)
    selected_subject = valid_positive_id(subject_id)
    selected_faculty = valid_positive_id(faculty_id)

    if entry_type in {"LECTURE", "LAB"}:
        if not selected_division or not selected_subject or not selected_faculty:
            return admin_error(
                "For a lecture or lab, select the class/division, subject, and faculty member."
            )

        if not title:
            title = entry_type.title()

    else:
        # General events do not require a class, subject, or faculty.
        selected_division = None
        selected_subject = None
        selected_faculty = None

        if not title:
            return admin_error("Enter a title for this timetable entry.")

    try:
        with get_connection() as conn:
            if entry_type in {"LECTURE", "LAB"}:
                faculty = conn.execute(
                    """
                    SELECT id, department_id
                    FROM faculty_profiles
                    WHERE id = ? AND is_active = 1
                    """,
                    (selected_faculty,),
                ).fetchone()

                subject = conn.execute(
                    """
                    SELECT id, department_id, semester_id
                    FROM subjects
                    WHERE id = ?
                    """,
                    (selected_subject,),
                ).fetchone()

                division = conn.execute(
                    """
                    SELECT id, department_id, semester_id
                    FROM divisions
                    WHERE id = ?
                    """,
                    (selected_division,),
                ).fetchone()

                if not faculty:
                    return admin_error(
                        "The selected faculty member does not exist or is inactive."
                    )

                if not subject or not division:
                    return admin_error("Select a valid subject and class/division.")

                if (
                    subject["department_id"] != division["department_id"]
                    or subject["semester_id"] != division["semester_id"]
                ):
                    return admin_error(
                        "The selected subject does not belong to the selected class's department and semester."
                    )

                if faculty["department_id"] != division["department_id"]:
                    return admin_error(
                        "The selected faculty member must belong to the class's department."
                    )

            conflict = timetable_overlap(
                conn,
                day_of_week,
                start_value,
                end_value,
                division_id=selected_division,
                faculty_id=selected_faculty,
            )

            if conflict:
                return admin_error(conflict)

            conn.execute(
                """
                INSERT INTO timetable (
                    division_id,
                    subject_id,
                    faculty_id,
                    day_of_week,
                    start_time,
                    end_time,
                    entry_type,
                    title
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    selected_division,
                    selected_subject,
                    selected_faculty,
                    day_of_week,
                    start_value,
                    end_value,
                    entry_type,
                    title,
                ),
            )

            # Automatically assign faculty to the subject and division.
            # This removes the need to create an assignment first.
            if entry_type in {"LECTURE", "LAB"}:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO faculty_assignments
                        (faculty_id, subject_id, division_id)
                    VALUES (?, ?, ?)
                    """,
                    (
                        selected_faculty,
                        selected_subject,
                        selected_division,
                    ),
                )

            conn.commit()

        return RedirectResponse("/admin/manage", status_code=303)

    except sqlite3.IntegrityError:
        return admin_error(
            "The timetable entry could not be saved because of a database constraint."
        )
    except sqlite3.Error:
        return admin_error("Unable to save the timetable entry.", 500)


# ---------------------------------------------------------
# CLASSES AND STUDENTS
# ---------------------------------------------------------

@router.get("/classes", response_class=HTMLResponse)
def admin_classes(request: Request):
    admin = ensure_admin(request)
    if not admin:
        return admin_redirect()

    try:
        with get_connection() as conn:
            classes = conn.execute(
                """
                SELECT v.*,
                       d.name AS department_name,
                       s.number AS semester_number,
                       (
                           SELECT COUNT(*)
                           FROM student_profiles sp
                           WHERE sp.division_id = v.id
                             AND sp.is_active = 1
                       ) AS student_count
                FROM divisions v
                JOIN departments d ON d.id = v.department_id
                JOIN semesters s ON s.id = v.semester_id
                ORDER BY d.name, s.number, v.name
                """
            ).fetchall()

        return templates.TemplateResponse(
            "admin_classes.html",
            {"request": request, "user": admin,"current_user": admin , "classes": classes},
        )
    except sqlite3.Error:
        return admin_error("Unable to load classes.", 500)


@router.get("/classes/{division_id}/students", response_class=HTMLResponse)
def admin_class_students(request: Request, division_id: int):
    admin = ensure_admin(request)
    if not admin:
        return admin_redirect()

    try:
        with get_connection() as conn:
            division = conn.execute(
                """
                SELECT v.*,
                       d.name AS department_name,
                       s.number AS semester_number
                FROM divisions v
                JOIN departments d ON d.id = v.department_id
                JOIN semesters s ON s.id = v.semester_id
                WHERE v.id = ?
                """,
                (division_id,),
            ).fetchone()

            if not division:
                return admin_error("Class/division not found.", 404)

            students = conn.execute(
                """
                SELECT *
                FROM student_profiles
                WHERE division_id = ? AND is_active = 1
                ORDER BY roll_number, name
                """,
                (division_id,),
            ).fetchall()

        return templates.TemplateResponse(
            "admin_students.html",
            {
                "request": request,
                "user": admin,
                "current_user": admin,
                "division": division,
                "class_info": division,
                "students": students,
            },
        )
    except sqlite3.Error:
        return admin_error("Unable to load students.", 500)


# ---------------------------------------------------------
# STUDENT DETAIL AND ATTENDANCE HISTORY
# ---------------------------------------------------------

@router.get("/students/{student_id}", response_class=HTMLResponse)
def admin_student_detail(request: Request, student_id: int):
    admin = ensure_admin(request)
    if not admin:
        return admin_redirect()

    try:
        with get_connection() as conn:
            student = conn.execute(
                """
                SELECT sp.*,
                       d.name AS department_name,
                       s.number AS semester_number,
                       v.name AS division_name
                FROM student_profiles sp
                LEFT JOIN departments d ON d.id = sp.department_id
                LEFT JOIN semesters s ON s.id = sp.semester_id
                LEFT JOIN divisions v ON v.id = sp.division_id
                WHERE sp.id = ?
                """,
                (student_id,),
            ).fetchone()

            if not student:
                return admin_error("Student not found.", 404)

            attendance_history = conn.execute(
                """
                SELECT ar.*,
                       ats.started_at,
                       ats.closed_at,
                       ats.lecture_date,
                       sub.name AS subject_name,
                       sub.code AS subject_code,
                       t.title AS timetable_title
                FROM attendance_records ar
                JOIN attendance_sessions ats ON ats.id = ar.session_id
                LEFT JOIN subjects sub ON sub.id = ats.subject_id
                LEFT JOIN timetable t ON t.id = ats.timetable_id
                WHERE ar.student_id = ?
                ORDER BY COALESCE(ats.lecture_date, date(ats.started_at)) DESC,
                         ar.marked_at DESC
                """,
                (student_id,),
            ).fetchall()

            leave_history = conn.execute(
                """
                SELECT lr.*,
                       sub.name AS subject_name,
                       sub.code AS subject_code,
                       v.name AS division_name,
                       f.name AS faculty_name
                FROM leave_requests lr
                LEFT JOIN timetable t ON t.id = lr.timetable_id
                LEFT JOIN subjects sub ON sub.id = t.subject_id
                LEFT JOIN divisions v ON v.id = t.division_id
                LEFT JOIN faculty_profiles f ON f.id = t.faculty_id
                WHERE lr.student_id = ?
                ORDER BY lr.submitted_at DESC
                """,
                (student_id,),
            ).fetchall()

        return templates.TemplateResponse(
            "admin_student_detail.html",
            {
                "request": request,
                "user": admin,
                "current_user": admin,
                "student": student,
                "attendance_history": attendance_history,
                "leave_history": leave_history,
                "attendance_records": attendance_history,
                "leave_requests": leave_history,
            },
        )
    except sqlite3.Error:
        return admin_error("Unable to load the student's history.", 500)


# ---------------------------------------------------------
# FACULTY DIRECTORY
# ---------------------------------------------------------

@router.get("/faculty", response_class=HTMLResponse)
def admin_faculty(request: Request):
    admin = ensure_admin(request)
    if not admin:
        return admin_redirect()

    try:
        with get_connection() as conn:
            faculty = conn.execute(
                """
                SELECT f.*,
                       d.name AS department_name,
                       (
                           SELECT COUNT(*)
                           FROM faculty_assignments fa
                           WHERE fa.faculty_id = f.id
                       ) AS assignment_count
                FROM faculty_profiles f
                LEFT JOIN departments d ON d.id = f.department_id
                WHERE f.is_active = 1
                ORDER BY f.name
                """
            ).fetchall()

            # Keep the existing template working if it is used for
            # both the management screen and faculty directory.
            departments = conn.execute(
                "SELECT * FROM departments ORDER BY name"
            ).fetchall()

            semesters = conn.execute(
                """
                SELECT s.*, d.name AS department_name, d.code AS department_code
                FROM semesters s
                JOIN departments d ON d.id = s.department_id
                ORDER BY d.name, s.number
                """
            ).fetchall()

            divisions = conn.execute(
                "SELECT * FROM divisions ORDER BY name"
            ).fetchall()

            subjects = conn.execute(
                "SELECT * FROM subjects ORDER BY name"
            ).fetchall()

            timetable = conn.execute(
                """
                SELECT t.*, v.name AS division_name,
                       sub.name AS subject_name, f.name AS faculty_name
                FROM timetable t
                LEFT JOIN divisions v ON v.id = t.division_id
                LEFT JOIN subjects sub ON sub.id = t.subject_id
                LEFT JOIN faculty_profiles f ON f.id = t.faculty_id
                ORDER BY t.day_of_week, t.start_time
                """
            ).fetchall()

        return templates.TemplateResponse(
            "admin_manage.html",
            {
                "request": request,
                "user": admin,
                "current_user": admin,
                "faculty": faculty,
                "departments": departments,
                "semesters": semesters,
                "divisions": divisions,
                "subjects": subjects,
                "timetable": timetable,
                "assignments": [],
                "settings": None,
                "college_settings": None,
            },
        )
    except sqlite3.Error:
        return admin_error("Unable to load the faculty directory.", 500)


# ---------------------------------------------------------
# COLLEGE LOCATION SETTINGS
# ---------------------------------------------------------

@router.get("/campus", response_class=HTMLResponse)
def campus_page(request: Request):
    admin = ensure_admin(request)
    if not admin:
        return admin_redirect()

    with get_connection() as conn:
        campus = conn.execute(
            "SELECT latitude, longitude, radius_meters FROM college_settings WHERE id = 1"
        ).fetchone()

    map_url = None
    if campus:
        lat, lon = campus["latitude"], campus["longitude"]
        d = 0.004
        map_url = (
            "https://www.openstreetmap.org/export/embed.html"
            f"?bbox={lon - d},{lat - d},{lon + d},{lat + d}&layer=mapnik&marker={lat},{lon}"
        )

    return templates.TemplateResponse(
        request=request,
        name="admin_campus.html",
        context={
            "current_user": admin,
            "configured": campus is not None,
            "radius": int(campus["radius_meters"]) if campus else 100,
            "map_url": map_url,
        },
    )


@router.post("/api/college-location")
async def update_college_location(request: Request):
    admin = ensure_admin(request)
    if not admin:
        return JSONResponse(
            {"success": False, "message": "Admin authentication required."},
            status_code=401,
        )

    try:
        data = await request.json()
        radius_meters = float(data.get("radius_meters", 100))

        if data.get("latitude") is None and data.get("longitude") is None:
            # Radius-only change: keep the saved campus point.
            with get_connection() as conn:
                saved = conn.execute(
                    "SELECT latitude, longitude FROM college_settings WHERE id = 1"
                ).fetchone()
            if not saved:
                return JSONResponse(
                    {"success": False, "message": "Set the campus location first."},
                    status_code=400,
                )
            latitude, longitude = saved["latitude"], saved["longitude"]
        else:
            latitude = float(data.get("latitude"))
            longitude = float(data.get("longitude"))

        if not (-90 <= latitude <= 90):
            return JSONResponse(
                {"success": False, "message": "Invalid latitude."},
                status_code=400,
            )

        if not (-180 <= longitude <= 180):
            return JSONResponse(
                {"success": False, "message": "Invalid longitude."},
                status_code=400,
            )

        if not (0 < radius_meters <= 10000):
            return JSONResponse(
                {"success": False, "message": "Radius must be between 1 and 10000 metres."},
                status_code=400,
            )

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO college_settings (id, latitude, longitude, radius_meters)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    radius_meters = excluded.radius_meters
                """,
                (latitude, longitude, radius_meters),
            )
            conn.commit()

        return JSONResponse(
            {
                "success": True,
                "message": "College location updated successfully.",
            }
        )

    except (TypeError, ValueError):
        return JSONResponse(
            {"success": False, "message": "Provide valid numeric location values."},
            status_code=400,
        )
    except sqlite3.Error:
        return JSONResponse(
            {"success": False, "message": "Unable to save college location."},
            status_code=500,
        )
    except Exception:
        return JSONResponse(
            {"success": False, "message": "Invalid request."},
            status_code=400,
        )