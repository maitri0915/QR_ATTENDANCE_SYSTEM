import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from templating import templates
from starlette.middleware.sessions import SessionMiddleware

from admin import router as admin_router
from faculty import router as faculty_router
from student import router as student_router
from fastapi.staticfiles import StaticFiles

from auth import (
    get_current_user,
    hash_password,
    login_user,
    logout_user,
    verify_password,
)
from database import get_connection, init_db


logger = logging.getLogger(__name__)

from config import APP_NAME, BASE_DIR, COOKIE_HTTPS_ONLY, SECRET_KEY



# ============================================================
# APPLICATION STARTUP
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from init_db import ensure_admin_from_env
    ensure_admin_from_env()
    yield


app = FastAPI(
    title=f"{APP_NAME} - QR Attendance",
    version="1.0.0",
    description="QR-based attendance management for colleges.",
    lifespan=lifespan,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="qr_attendance_session",
    max_age=60 * 60 * 8,
    same_site="lax",
    https_only=COOKIE_HTTPS_ONLY,
)

app.include_router(admin_router)
app.include_router(faculty_router)
app.include_router(student_router)

def _expose_api_at_root():
    """The page scripts call /api/... while each role router is mounted under
    its own prefix (/student, /faculty). Publish the API routes at the root
    as well so both URL styles work."""
    existing = {(route.path, m) for route in app.routes
                for m in getattr(route, "methods", None) or ()}
    for router in (faculty_router, student_router):
        for route in list(router.routes):
            marker = router.prefix + "/api/"
            if not route.path.startswith(marker):
                continue
            root_path = route.path[len(router.prefix):]
            methods = set(route.methods)
            if any((root_path, m) in existing for m in methods):
                continue
            app.add_api_route(root_path, route.endpoint,
                              methods=sorted(methods), include_in_schema=False)
            existing.update((root_path, m) for m in methods)


_expose_api_at_root()

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


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
            SELECT id, department_id, number
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
            SELECT id, department_id, semester_id, name
            FROM divisions
            ORDER BY department_id, semester_id, name
            """
        ).fetchall()
    finally:
        conn.close()


def registration_context(role, error=None):
    """Build the appropriate registration-page context."""
    context = {
        "current_user": None,
        "error": error,
        "departments": get_departments(),
    }

    if role == "student":
        context["semesters"] = get_semesters()
        context["divisions"] = get_divisions()

    return context


def render_registration_error(request, role, message):
    template_name = (
        "faculty_register.html"
        if role == "faculty"
        else "student_register.html"
    )

    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=registration_context(role, message),
        status_code=400,
    )


def email_exists(conn, email):
    """Check all account types before registering an account."""
    for table in (
        "admins",
        "faculty_profiles",
        "student_profiles",
    ):
        row = conn.execute(
            f"""
            SELECT id
            FROM {table}
            WHERE email = ? COLLATE NOCASE
            LIMIT 1
            """,
            (email,),
        ).fetchone()

        if row:
            return True

    return False


def login_page(request, role, role_name, error=None):
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



def authenticate_account(request, role, email, password):
    """Validate credentials and establish the role-specific session."""

    email = email.strip().lower()

    tables = {
        "admin": "admins",
        "faculty": "faculty_profiles",
        "student": "student_profiles",
    }

    if role not in tables:
        return "Invalid account role."

    conn = get_connection()

    try:
        row = conn.execute(
            f"""
            SELECT id, name, email, password_hash, is_active
            FROM {tables[role]}
            WHERE email = ? COLLATE NOCASE
            LIMIT 1
            """,
            (email,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return "Invalid email or password."

    # Convert SQLite Row into a regular Python dictionary.
    account = dict(row)

    if account["is_active"] != 1:
        return "This account is inactive."

    if not verify_password(password, account["password_hash"]):
        return "Invalid email or password."

    # login_user expects a dictionary.
    login_user(request, account, role)
    return None


# ============================================================
# HOME AND HEALTH CHECK
# ============================================================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    current_user = get_current_user(request)

    if current_user:
        return RedirectResponse("/dashboard", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"current_user": None},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)

    return login_page(request, "admin", "Admin")


@app.post("/admin/login", response_class=HTMLResponse)
def admin_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    error = authenticate_account(
        request, "admin", email, password
    )

    if error:
        return login_page(request, "admin", "Admin", error)

    return RedirectResponse("/dashboard", status_code=303)


# ============================================================
# FACULTY REGISTRATION PAGE
# ============================================================

@app.get("/faculty/register", response_class=HTMLResponse)
def faculty_register_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="faculty_register.html",
        context=registration_context("faculty"),
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
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)

    name = name.strip()
    employee_id = employee_id.strip()
    email = email.strip().lower()

    if len(name) < 2:
        return render_registration_error(
            request, "faculty", "Please enter a valid name."
        )

    if not employee_id or len(employee_id) > 50:
        return render_registration_error(
            request, "faculty", "Please enter a valid employee ID."
        )

    if len(email) > 254 or "@" not in email:
        return render_registration_error(
            request, "faculty", "Please enter a valid email address."
        )

    if len(password) < 8:
        return render_registration_error(
            request, "faculty",
            "Password must contain at least 8 characters.",
        )

    conn = get_connection()

    try:
        department = conn.execute(
            "SELECT id FROM departments WHERE id = ?",
            (department_id,),
        ).fetchone()

        if not department:
            return render_registration_error(
                request, "faculty",
                "Selected department does not exist.",
            )

        if email_exists(conn, email):
            return render_registration_error(
                request, "faculty",
                "This email is already registered.",
            )

        existing_employee = conn.execute(
            """
            SELECT id
            FROM faculty_profiles
            WHERE employee_id = ? COLLATE NOCASE
            """,
            (employee_id,),
        ).fetchone()

        if existing_employee:
            return render_registration_error(
                request, "faculty",
                "This employee ID is already registered.",
            )

        conn.execute(
            """
            INSERT INTO faculty_profiles
            (
                name, email, password_hash, employee_id,
                department_id, is_active
            )
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (
                name,
                email,
                hash_password(password),
                employee_id,
                department_id,
            ),
        )
        conn.commit()

    except Exception:
        conn.rollback()
        logger.exception("Faculty registration failed")
        return render_registration_error(
            request, "faculty",
            "Registration failed. Please check your details.",
        )
    finally:
        conn.close()

    return RedirectResponse("/faculty/login", status_code=303)


# ============================================================
# STUDENT REGISTRATION PAGE
# ============================================================

@app.get("/student/register", response_class=HTMLResponse)
def student_register_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="student_register.html",
        context=registration_context("student"),
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
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)

    name = name.strip()
    roll_number = roll_number.strip()
    email = email.strip().lower()

    if len(name) < 2:
        return render_registration_error(
            request, "student", "Please enter a valid name."
        )

    if not roll_number or len(roll_number) > 50:
        return render_registration_error(
            request, "student", "Please enter a valid roll number."
        )

    if len(email) > 254 or "@" not in email:
        return render_registration_error(
            request, "student", "Please enter a valid email address."
        )

    if len(password) < 8:
        return render_registration_error(
            request, "student",
            "Password must contain at least 8 characters.",
        )

    conn = get_connection()

    try:
        department = conn.execute(
            "SELECT id FROM departments WHERE id = ?",
            (department_id,),
        ).fetchone()

        if not department:
            return render_registration_error(
                request, "student",
                "Selected department does not exist.",
            )

        semester = conn.execute(
            """
            SELECT id
            FROM semesters
            WHERE id = ?
              AND department_id = ?
            """,
            (semester_id, department_id),
        ).fetchone()

        if not semester:
            return render_registration_error(
                request, "student",
                "Selected semester does not belong to the department.",
            )

        division = conn.execute(
            """
            SELECT id
            FROM divisions
            WHERE id = ?
              AND department_id = ?
              AND semester_id = ?
            """,
            (division_id, department_id, semester_id),
        ).fetchone()

        if not division:
            return render_registration_error(
                request, "student",
                "Selected division does not match the department and semester.",
            )

        if email_exists(conn, email):
            return render_registration_error(
                request, "student",
                "This email is already registered.",
            )

        existing_roll = conn.execute(
            """
            SELECT id
            FROM student_profiles
            WHERE roll_number = ? COLLATE NOCASE
            """,
            (roll_number,),
        ).fetchone()

        if existing_roll:
            return render_registration_error(
                request, "student",
                "This roll number is already registered.",
            )

        conn.execute(
            """
            INSERT INTO student_profiles
            (
                name, email, password_hash, roll_number,
                department_id, semester_id, division_id, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                name,
                email,
                hash_password(password),
                roll_number,
                department_id,
                semester_id,
                division_id,
            ),
        )
        conn.commit()

    except Exception:
        conn.rollback()
        logger.exception("Student registration failed")
        return render_registration_error(
            request, "student",
            "Registration failed. Please check your details.",
        )
    finally:
        conn.close()

    return RedirectResponse("/student/login", status_code=303)


# ============================================================
# FACULTY LOGIN
# ============================================================

@app.get("/faculty/login", response_class=HTMLResponse)
def faculty_login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)

    return login_page(request, "faculty", "Faculty")


@app.post("/faculty/login", response_class=HTMLResponse)
def faculty_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    error = authenticate_account(
        request, "faculty", email, password
    )

    if error:
        return login_page(request, "faculty", "Faculty", error)

    return RedirectResponse("/dashboard", status_code=303)


# ============================================================
# STUDENT LOGIN
# ============================================================

@app.get("/student/login", response_class=HTMLResponse)
def student_login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)

    return login_page(request, "student", "Student")


@app.post("/student/login", response_class=HTMLResponse)
def student_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    error = authenticate_account(
        request, "student", email, password
    )

    if error:
        return login_page(request, "student", "Student", error)

    return RedirectResponse("/dashboard", status_code=303)


# ============================================================
# ROLE-BASED DASHBOARD
# ============================================================

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    current_user = get_current_user(request)

    if not current_user:
        return RedirectResponse("/", status_code=303)

    if current_user["role"] == "admin":
        return RedirectResponse("/admin/dashboard", status_code=303)

    if current_user["role"] == "faculty":
        return RedirectResponse("/faculty/dashboard", status_code=303)

    counts = {
        "departments": 0,
        "faculty": 0,
        "students": 0,
    }

    if current_user["role"] == "admin":
        conn = get_connection()

        try:
            counts["departments"] = conn.execute(
                "SELECT COUNT(*) FROM departments"
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
            "title": f"{current_user['role'].capitalize()} Dashboard",
            "counts": counts,
        },
    )


# ============================================================
# LOGOUT
# ============================================================

@app.get("/logout")
def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/", status_code=303)