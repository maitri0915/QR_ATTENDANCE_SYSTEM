from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from admin import router as admin_router
from faculty import router as faculty_router
from student import router as student_router

from auth import (
    get_current_user,
    hash_password,
    login_user,
    logout_user,
    verify_password,
)
from database import get_connection, init_db


SECRET_KEY = "CHANGE-THIS-DEVELOPMENT-SECRET-KEY"


templates = Jinja2Templates(
    directory="templates"
)


# ============================================================
# APPLICATION STARTUP
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="QR Attendance and Management System",
    version="1.0.0",
    description="College diploma minor project using FastAPI and SQLite.",
    lifespan=lifespan,
)


app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="qr_attendance_session",
    max_age=60 * 60 * 8,
    same_site="lax",
    https_only=False,
)


app.include_router(admin_router)
app.include_router(faculty_router)
app.include_router(student_router)


# ============================================================
# COMMON DATABASE HELPERS
# ============================================================

def get_departments():
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT id, name, code
            FROM departments
            ORDER BY name
            """
        ).fetchall()

    finally:
        conn.close()


def get_semesters():
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT
                id,
                department_id,
                number
            FROM semesters
            ORDER BY department_id, number
            """
        ).fetchall()

    finally:
        conn.close()


def get_divisions():
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT
                id,
                department_id,
                semester_id,
                name
            FROM divisions
            ORDER BY department_id, semester_id, name
            """
        ).fetchall()

    finally:
        conn.close()


# ============================================================
# HOME
# ============================================================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):

    current_user = get_current_user(request)

    if current_user:
        return RedirectResponse(
            url="/dashboard",
            status_code=303,
        )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "current_user": None
        },
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():
    return {
        "status": "ok"
    }


# ============================================================
# LOGIN PAGE HELPER
# ============================================================

def login_page(
    request: Request,
    role: str,
    role_name: str,
    error: str | None = None,
):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "current_user": get_current_user(request),
            "role": role,
            "role_name": role_name,
            "error": error,
        },
    )


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):

    current_user = get_current_user(request)

    if current_user:
        return RedirectResponse(
            url="/dashboard",
            status_code=303,
        )

    return login_page(
        request=request,
        role="admin",
        role_name="Admin",
    )


@app.post("/admin/login", response_class=HTMLResponse)
def admin_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):

    email = email.strip().lower()

    conn = get_connection()

    try:
        admin = conn.execute(
            """
            SELECT
                id,
                name,
                email,
                password_hash,
                is_active
            FROM admins
            WHERE email = ? COLLATE NOCASE
            """,
            (email,),
        ).fetchone()

    finally:
        conn.close()

    if admin is None:
        return login_page(
            request,
            "admin",
            "Admin",
            "Invalid email or password.",
        )

    if admin["is_active"] != 1:
        return login_page(
            request,
            "admin",
            "Admin",
            "This account is inactive.",
        )

    if not verify_password(
        password,
        admin["password_hash"]
    ):
        return login_page(
            request,
            "admin",
            "Admin",
            "Invalid email or password.",
        )

    login_user(
        request,
        admin,
        "admin",
    )

    return RedirectResponse(
        url="/dashboard",
        status_code=303,
    )


# ============================================================
# FACULTY REGISTRATION PAGE
# ============================================================

@app.get("/faculty/register", response_class=HTMLResponse)
def faculty_register_page(request: Request):

    current_user = get_current_user(request)

    if current_user:
        return RedirectResponse(
            url="/dashboard",
            status_code=303,
        )

    return templates.TemplateResponse(
        request=request,
        name="faculty_register.html",
        context={
            "current_user": None,
            "departments": get_departments(),
            "error": None,
        },
    )


# ============================================================
# FACULTY REGISTRATION
# ============================================================

@app.post("/faculty/register", response_class=HTMLResponse)
def faculty_register(
    request: Request,
    name: str = Form(...),
    employee_id: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    department_id: int = Form(...),
):

    name = name.strip()
    employee_id = employee_id.strip()
    email = email.strip().lower()

    page_context = {
        "current_user": None,
        "departments": get_departments(),
        "error": None,
    }

    if len(name) < 2:
        page_context["error"] = "Please enter a valid name."

        return templates.TemplateResponse(
            request=request,
            name="faculty_register.html",
            context=page_context,
        )

    if len(password) < 8:
        page_context["error"] = (
            "Password must contain at least 8 characters."
        )

        return templates.TemplateResponse(
            request=request,
            name="faculty_register.html",
            context=page_context,
        )

    conn = get_connection()

    try:

        # ----------------------------------------------------
        # Validate department
        # ----------------------------------------------------

        department = conn.execute(
            """
            SELECT id
            FROM departments
            WHERE id = ?
            """,
            (department_id,),
        ).fetchone()

        if department is None:
            page_context["error"] = (
                "Selected department does not exist."
            )

            return templates.TemplateResponse(
                request=request,
                name="faculty_register.html",
                context=page_context,
            )

        # ----------------------------------------------------
        # Check email across faculty and students
        # ----------------------------------------------------

        existing_faculty_email = conn.execute(
            """
            SELECT id
            FROM faculty_profiles
            WHERE email = ? COLLATE NOCASE
            """,
            (email,),
        ).fetchone()

        existing_student_email = conn.execute(
            """
            SELECT id
            FROM student_profiles
            WHERE email = ? COLLATE NOCASE
            """,
            (email,),
        ).fetchone()

        existing_admin_email = conn.execute(
            """
            SELECT id
            FROM admins
            WHERE email = ? COLLATE NOCASE
            """,
            (email,),
        ).fetchone()

        if (
            existing_faculty_email
            or existing_student_email
            or existing_admin_email
        ):
            page_context["error"] = (
                "This email is already registered."
            )

            return templates.TemplateResponse(
                request=request,
                name="faculty_register.html",
                context=page_context,
            )

        # ----------------------------------------------------
        # Check employee ID
        # ----------------------------------------------------

        existing_employee = conn.execute(
            """
            SELECT id
            FROM faculty_profiles
            WHERE employee_id = ? COLLATE NOCASE
            """,
            (employee_id,),
        ).fetchone()

        if existing_employee:
            page_context["error"] = (
                "This employee ID is already registered."
            )

            return templates.TemplateResponse(
                request=request,
                name="faculty_register.html",
                context=page_context,
            )

        # ----------------------------------------------------
        # Create faculty profile
        # ----------------------------------------------------

        password_hash = hash_password(password)

        conn.execute(
            """
            INSERT INTO faculty_profiles
            (
                name,
                email,
                password_hash,
                employee_id,
                department_id,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (
                name,
                email,
                password_hash,
                employee_id,
                department_id,
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()

        page_context["error"] = (
            "Registration failed. Please check your details."
        )

        return templates.TemplateResponse(
            request=request,
            name="faculty_register.html",
            context=page_context,
        )

    finally:
        conn.close()

    return RedirectResponse(
        url="/faculty/login",
        status_code=303,
    )


# ============================================================
# STUDENT REGISTRATION PAGE
# ============================================================

@app.get("/student/register", response_class=HTMLResponse)
def student_register_page(request: Request):

    current_user = get_current_user(request)

    if current_user:
        return RedirectResponse(
            url="/dashboard",
            status_code=303,
        )

    return templates.TemplateResponse(
        request=request,
        name="student_register.html",
        context={
            "current_user": None,
            "departments": get_departments(),
            "semesters": get_semesters(),
            "divisions": get_divisions(),
            "error": None,
        },
    )


# ============================================================
# STUDENT REGISTRATION
# ============================================================

@app.post("/student/register", response_class=HTMLResponse)
def student_register(
    request: Request,
    name: str = Form(...),
    roll_number: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    department_id: int = Form(...),
    semester_id: int = Form(...),
    division_id: int = Form(...),
):

    name = name.strip()
    roll_number = roll_number.strip()
    email = email.strip().lower()

    page_context = {
        "current_user": None,
        "departments": get_departments(),
        "semesters": get_semesters(),
        "divisions": get_divisions(),
        "error": None,
    }

    if len(name) < 2:
        page_context["error"] = "Please enter a valid name."

        return templates.TemplateResponse(
            request=request,
            name="student_register.html",
            context=page_context,
        )

    if len(password) < 8:
        page_context["error"] = (
            "Password must contain at least 8 characters."
        )

        return templates.TemplateResponse(
            request=request,
            name="student_register.html",
            context=page_context,
        )

    conn = get_connection()

    try:

        # ----------------------------------------------------
        # Validate department
        # ----------------------------------------------------

        department = conn.execute(
            """
            SELECT id
            FROM departments
            WHERE id = ?
            """,
            (department_id,),
        ).fetchone()

        if department is None:
            page_context["error"] = (
                "Selected department does not exist."
            )

            return templates.TemplateResponse(
                request=request,
                name="student_register.html",
                context=page_context,
            )

        # ----------------------------------------------------
        # Validate semester
        # ----------------------------------------------------

        semester = conn.execute(
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

        if semester is None:
            page_context["error"] = (
                "Selected semester does not belong to "
                "the selected department."
            )

            return templates.TemplateResponse(
                request=request,
                name="student_register.html",
                context=page_context,
            )

        # ----------------------------------------------------
        # Validate division
        # ----------------------------------------------------

        division = conn.execute(
            """
            SELECT id
            FROM divisions
            WHERE id = ?
              AND department_id = ?
              AND semester_id = ?
            """,
            (
                division_id,
                department_id,
                semester_id,
            ),
        ).fetchone()

        if division is None:
            page_context["error"] = (
                "Selected division does not belong to "
                "the selected department and semester."
            )

            return templates.TemplateResponse(
                request=request,
                name="student_register.html",
                context=page_context,
            )

        # ----------------------------------------------------
        # Check email across all account tables
        # ----------------------------------------------------

        existing_admin_email = conn.execute(
            """
            SELECT id
            FROM admins
            WHERE email = ? COLLATE NOCASE
            """,
            (email,),
        ).fetchone()

        existing_faculty_email = conn.execute(
            """
            SELECT id
            FROM faculty_profiles
            WHERE email = ? COLLATE NOCASE
            """,
            (email,),
        ).fetchone()

        existing_student_email = conn.execute(
            """
            SELECT id
            FROM student_profiles
            WHERE email = ? COLLATE NOCASE
            """,
            (email,),
        ).fetchone()

        if (
            existing_admin_email
            or existing_faculty_email
            or existing_student_email
        ):
            page_context["error"] = (
                "This email is already registered."
            )

            return templates.TemplateResponse(
                request=request,
                name="student_register.html",
                context=page_context,
            )

        # ----------------------------------------------------
        # Check roll number
        # ----------------------------------------------------

        existing_roll = conn.execute(
            """
            SELECT id
            FROM student_profiles
            WHERE roll_number = ? COLLATE NOCASE
            """,
            (roll_number,),
        ).fetchone()

        if existing_roll:
            page_context["error"] = (
                "This roll number is already registered."
            )

            return templates.TemplateResponse(
                request=request,
                name="student_register.html",
                context=page_context,
            )

        # ----------------------------------------------------
        # Create student profile
        # ----------------------------------------------------

        password_hash = hash_password(password)

        conn.execute(
            """
            INSERT INTO student_profiles
            (
                name,
                email,
                password_hash,
                roll_number,
                department_id,
                semester_id,
                division_id,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                name,
                email,
                password_hash,
                roll_number,
                department_id,
                semester_id,
                division_id,
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()

        page_context["error"] = (
            "Registration failed. Please check your details."
        )

        return templates.TemplateResponse(
            request=request,
            name="student_register.html",
            context=page_context,
        )

    finally:
        conn.close()

    return RedirectResponse(
        url="/student/login",
        status_code=303,
    )


# ============================================================
# FACULTY LOGIN PAGE
# ============================================================

@app.get("/faculty/login", response_class=HTMLResponse)
def faculty_login_page(request: Request):

    current_user = get_current_user(request)

    if current_user:
        return RedirectResponse(
            url="/dashboard",
            status_code=303,
        )

    return login_page(
        request=request,
        role="faculty",
        role_name="Faculty",
    )


# ============================================================
# FACULTY LOGIN
# ============================================================

@app.post("/faculty/login", response_class=HTMLResponse)
def faculty_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):

    email = email.strip().lower()

    conn = get_connection()

    try:
        faculty = conn.execute(
            """
            SELECT
                id,
                name,
                email,
                password_hash,
                is_active
            FROM faculty_profiles
            WHERE email = ? COLLATE NOCASE
            """,
            (email,),
        ).fetchone()

    finally:
        conn.close()

    if faculty is None:
        return login_page(
            request,
            "faculty",
            "Faculty",
            "Invalid email or password.",
        )

    if faculty["is_active"] != 1:
        return login_page(
            request,
            "faculty",
            "Faculty",
            "This account is inactive.",
        )

    if not verify_password(
        password,
        faculty["password_hash"]
    ):
        return login_page(
            request,
            "faculty",
            "Faculty",
            "Invalid email or password.",
        )

    login_user(
        request,
        faculty,
        "faculty",
    )

    return RedirectResponse(
        url="/dashboard",
        status_code=303,
    )


# ============================================================
# STUDENT LOGIN PAGE
# ============================================================

@app.get("/student/login", response_class=HTMLResponse)
def student_login_page(request: Request):

    current_user = get_current_user(request)

    if current_user:
        return RedirectResponse(
            url="/dashboard",
            status_code=303,
        )

    return login_page(
        request=request,
        role="student",
        role_name="Student",
    )


# ============================================================
# STUDENT LOGIN
# ============================================================

@app.post("/student/login", response_class=HTMLResponse)
def student_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):

    email = email.strip().lower()

    conn = get_connection()

    try:
        student = conn.execute(
            """
            SELECT
                id,
                name,
                email,
                password_hash,
                is_active
            FROM student_profiles
            WHERE email = ? COLLATE NOCASE
            """,
            (email,),
        ).fetchone()

    finally:
        conn.close()

    if student is None:
        return login_page(
            request,
            "student",
            "Student",
            "Invalid email or password.",
        )

    if student["is_active"] != 1:
        return login_page(
            request,
            "student",
            "Student",
            "This account is inactive.",
        )

    if not verify_password(
        password,
        student["password_hash"]
    ):
        return login_page(
            request,
            "student",
            "Student",
            "Invalid email or password.",
        )

    login_user(
        request,
        student,
        "student",
    )

    return RedirectResponse(
        url="/dashboard",
        status_code=303,
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):

    current_user = get_current_user(request)

    if current_user is None:
        return RedirectResponse(
            url="/",
            status_code=303,
        )

    counts = {
        "departments": 0,
        "faculty": 0,
        "students": 0,
    }

    if current_user["role"] == "admin":

        conn = get_connection()

        try:

            counts["departments"] = conn.execute(
                """
                SELECT COUNT(*)
                FROM departments
                """
            ).fetchone()[0]

            counts["faculty"] = conn.execute(
                """
                SELECT COUNT(*)
                FROM faculty_profiles
                WHERE is_active = 1
                """
            ).fetchone()[0]

            counts["students"] = conn.execute(
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
        name="dashboard.html",
        context={
            "current_user": current_user,
            "title": (
                f"{current_user['role'].capitalize()} Dashboard"
            ),
            "counts": counts,
        },
    )


# ============================================================
# LOGOUT
# ============================================================

@app.get("/logout")
def logout(request: Request):

    logout_user(request)

    return RedirectResponse(
        url="/",
        status_code=303,
    )