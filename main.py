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


@app.get("/health")
def health():
    return {
        "status": "ok"
    }


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

    if len(name) < 2:
        return templates.TemplateResponse(
            request=request,
            name="faculty_register.html",
            context={
                "current_user": None,
                "departments": get_departments(),
                "error": "Please enter a valid name.",
            },
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            request=request,
            name="faculty_register.html",
            context={
                "current_user": None,
                "departments": get_departments(),
                "error": "Password must contain at least 8 characters.",
            },
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
            return templates.TemplateResponse(
                request=request,
                name="faculty_register.html",
                context={
                    "current_user": None,
                    "departments": get_departments(),
                    "error": "Selected department does not exist.",
                },
            )

        existing_email = conn.execute(
            """
            SELECT id
            FROM users
            WHERE email = ? COLLATE NOCASE
            """,
            (email,),
        ).fetchone()

        if existing_email:
            return templates.TemplateResponse(
                request=request,
                name="faculty_register.html",
                context={
                    "current_user": None,
                    "departments": get_departments(),
                    "error": "This email is already registered.",
                },
            )

        existing_employee = conn.execute(
            """
            SELECT user_id
            FROM faculty_profiles
            WHERE employee_id = ? COLLATE NOCASE
            """,
            (employee_id,),
        ).fetchone()

        if existing_employee:
            return templates.TemplateResponse(
                request=request,
                name="faculty_register.html",
                context={
                    "current_user": None,
                    "departments": get_departments(),
                    "error": "This employee ID is already registered.",
                },
            )

        password_hash = hash_password(password)

        cursor = conn.execute(
            """
            INSERT INTO users
            (
                name,
                email,
                password_hash,
                role
            )
            VALUES (?, ?, ?, 'faculty')
            """,
            (
                name,
                email,
                password_hash,
            ),
        )

        user_id = cursor.lastrowid

        conn.execute(
            """
            INSERT INTO faculty_profiles
            (
                user_id,
                employee_id,
                department_id
            )
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                employee_id,
                department_id,
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()

        return templates.TemplateResponse(
            request=request,
            name="faculty_register.html",
            context={
                "current_user": None,
                "departments": get_departments(),
                "error": "Registration failed. Please check your details.",
            },
        )

    finally:
        conn.close()

    return RedirectResponse(
        url="/faculty/login",
        status_code=303,
    )

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

        # ---------------------------------------------------------
        # Validate department
        # ---------------------------------------------------------

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

        # ---------------------------------------------------------
        # Validate semester belongs to department
        # ---------------------------------------------------------

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

        # ---------------------------------------------------------
        # Validate division belongs to department + semester
        # ---------------------------------------------------------

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

        # ---------------------------------------------------------
        # Check email
        # ---------------------------------------------------------

        existing_email = conn.execute(
            """
            SELECT id
            FROM users
            WHERE email = ? COLLATE NOCASE
            """,
            (email,),
        ).fetchone()

        if existing_email:
            page_context["error"] = (
                "This email is already registered."
            )

            return templates.TemplateResponse(
                request=request,
                name="student_register.html",
                context=page_context,
            )

        # ---------------------------------------------------------
        # Check roll number
        # ---------------------------------------------------------

        existing_roll = conn.execute(
            """
            SELECT user_id
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

        # ---------------------------------------------------------
        # Create user
        # ---------------------------------------------------------

        password_hash = hash_password(password)

        cursor = conn.execute(
            """
            INSERT INTO users
            (
                name,
                email,
                password_hash,
                role
            )
            VALUES (?, ?, ?, 'student')
            """,
            (
                name,
                email,
                password_hash,
            ),
        )

        user_id = cursor.lastrowid

        # ---------------------------------------------------------
        # Create student profile
        # ---------------------------------------------------------

        conn.execute(
            """
            INSERT INTO student_profiles
            (
                user_id,
                roll_number,
                department_id,
                semester_id,
                division_id
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
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

@app.post("/admin/login", response_class=HTMLResponse)
def admin_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):

    conn = get_connection()

    try:
        user = conn.execute(
            """
            SELECT
                id,
                name,
                email,
                password_hash,
                role,
                is_active
            FROM users
            WHERE email = ? COLLATE NOCASE
              AND role = 'admin'
            """,
            (email.strip(),),
        ).fetchone()

    finally:
        conn.close()

    if user is None:
        return login_page(
            request,
            "admin",
            "Admin",
            "Invalid email or password.",
        )

    if user["is_active"] != 1:
        return login_page(
            request,
            "admin",
            "Admin",
            "This account is inactive.",
        )

    if not verify_password(password, user["password_hash"]):
        return login_page(
            request,
            "admin",
            "Admin",
            "Invalid email or password.",
        )

    login_user(request, user)

    return RedirectResponse(
        url="/dashboard",
        status_code=303,
    )


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


@app.post("/faculty/login", response_class=HTMLResponse)
def faculty_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):

    conn = get_connection()

    try:
        user = conn.execute(
            """
            SELECT
                id,
                name,
                email,
                password_hash,
                role,
                is_active
            FROM users
            WHERE email = ? COLLATE NOCASE
              AND role = 'faculty'
            """,
            (email.strip(),),
        ).fetchone()

    finally:
        conn.close()

    if user is None:
        return login_page(
            request,
            "faculty",
            "Faculty",
            "Invalid email or password.",
        )

    if user["is_active"] != 1:
        return login_page(
            request,
            "faculty",
            "Faculty",
            "This account is inactive.",
        )

    if not verify_password(password, user["password_hash"]):
        return login_page(
            request,
            "faculty",
            "Faculty",
            "Invalid email or password.",
        )

    login_user(request, user)

    return RedirectResponse(
        url="/dashboard",
        status_code=303,
    )


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


@app.post("/student/login", response_class=HTMLResponse)
def student_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):

    conn = get_connection()

    try:
        user = conn.execute(
            """
            SELECT
                id,
                name,
                email,
                password_hash,
                role,
                is_active
            FROM users
            WHERE email = ? COLLATE NOCASE
              AND role = 'student'
            """,
            (email.strip(),),
        ).fetchone()

    finally:
        conn.close()

    if user is None:
        return login_page(
            request,
            "student",
            "Student",
            "Invalid email or password.",
        )

    if user["is_active"] != 1:
        return login_page(
            request,
            "student",
            "Student",
            "This account is inactive.",
        )

    if not verify_password(password, user["password_hash"]):
        return login_page(
            request,
            "student",
            "Student",
            "Invalid email or password.",
        )

    login_user(request, user)

    return RedirectResponse(
        url="/dashboard",
        status_code=303,
    )


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
                FROM users
                WHERE role = 'faculty'
                """
            ).fetchone()[0]

            counts["students"] = conn.execute(
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
        name="dashboard.html",
        context={
            "current_user": current_user,
            "title": (
                f"{current_user['role'].capitalize()} Dashboard"
            ),
            "counts": counts,
        },
    )


@app.get("/logout")
def logout(request: Request):

    logout_user(request)

    return RedirectResponse(
        url="/",
        status_code=303,
    )