import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from templating import templates
from starlette.middleware.sessions import SessionMiddleware

import platform_db
from admin import router as admin_router
from middleware import TenantMiddleware
from platform_admin import router as platform_router
from tenancy import TenantNotSelected, current_tenant, use_tenant
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
    platform_db.init_platform_db()
    from init_db import ensure_platform_admin_from_env
    ensure_platform_admin_from_env()
    platform_db.migrate_legacy_database()
    # Apply (idempotent) schema updates to every university database.
    for tenant in platform_db.list_active_tenants():
        init_db(tenant.db_path)
    yield


app = FastAPI(
    title=f"{APP_NAME} - QR Attendance",
    version="1.0.0",
    description="Multi-university QR attendance management platform.",
    lifespan=lifespan,
)

# Order matters: the last middleware added is the outermost. SessionMiddleware
# must wrap TenantMiddleware so the session is loaded before the tenant lookup.
app.add_middleware(TenantMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="qr_attendance_session",
    max_age=60 * 60 * 8,
    same_site="lax",
    https_only=COOKIE_HTTPS_ONLY,
)

app.include_router(platform_router)
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

@app.exception_handler(TenantNotSelected)
async def _tenant_not_selected(request: Request, exc: TenantNotSelected):
    return RedirectResponse("/", status_code=303)


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ============================================================
# COMMON DATABASE HELPERS
# ============================================================

# ============================================================
# UNIVERSITY SELECTION
# ============================================================

def resolve_tenant(u: str):
    """Pick the university for a public (signed-out) page.

    Returns (tenant, message). With no `u` and exactly one active university
    that university is used, so single-university deployments keep their
    old URLs. Otherwise the caller shows the university chooser."""
    u = (u or "").strip().lower()
    if u:
        tenant = platform_db.get_active_tenant(u)
        if tenant:
            return tenant, None
        return None, "That university is not available."
    active = platform_db.list_active_tenants()
    if len(active) == 1:
        return active[0], None
    return None, None


def university_chooser(request, action_path, message=None):
    return templates.TemplateResponse(
        request=request,
        name="select_university.html",
        context={
            "universities": platform_db.list_active_tenants(),
            "action_path": action_path,
            "message": message,
        },
    )


def tenant_url(path):
    """`path` with the current university attached (?u=slug)."""
    tenant = current_tenant()
    return f"{path}?u={tenant.slug}" if tenant else path


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
        context={
            **registration_context(role, message),
            "university_slug": current_tenant().slug,
        },
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
    tenant = current_tenant()
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "current_user": get_current_user(request),
            "role": role,
            "role_name": role_name,
            "error": error,
            "university_slug": tenant.slug if tenant else "",
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
    login_user(request, account, role, university=current_tenant().slug)
    return None


# ============================================================
# HOME AND HEALTH CHECK
# ============================================================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    current_user = get_current_user(request)

    if current_user:
        return RedirectResponse("/dashboard", status_code=303)

    notice = None
    if request.query_params.get("notice") == "university-unavailable":
        notice = ("Your university's account is not currently active. "
                  "Please contact your university administrator.")
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"current_user": None, "notice": notice},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request, u: str = Query("")):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)

    tenant, message = resolve_tenant(u)
    if tenant is None:
        return university_chooser(request, "/admin/login", message)

    with use_tenant(tenant):
        return login_page(request, "admin", "Admin")


@app.post("/admin/login", response_class=HTMLResponse)
def admin_login(
    request: Request,
    u: str = Query(""),
    email: str = Form(...),
    password: str = Form(...),
):
    tenant, message = resolve_tenant(u)
    if tenant is None:
        return university_chooser(request, "/admin/login", message)

    with use_tenant(tenant):
        error = authenticate_account(request, "admin", email, password)
        if error:
            return login_page(request, "admin", "Admin", error)

    return RedirectResponse("/dashboard", status_code=303)


# ============================================================
# FACULTY REGISTRATION PAGE
# ============================================================

@app.get("/faculty/register", response_class=HTMLResponse)
def faculty_register_page(request: Request, u: str = Query("")):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)

    tenant, message = resolve_tenant(u)
    if tenant is None:
        return university_chooser(request, "/faculty/register", message)

    with use_tenant(tenant):
        return templates.TemplateResponse(
            request=request,
            name="faculty_register.html",
            context={**registration_context("faculty"), "university_slug": tenant.slug},
        )


# ============================================================
# FACULTY REGISTRATION
# ============================================================

@app.post("/faculty/register", response_class=HTMLResponse)
def faculty_register_route(
    request: Request,
    u: str = Query(""),
    name: str = Form(...),
    employee_id: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    department_id: int = Form(...),
):
    tenant, message = resolve_tenant(u)
    if tenant is None:
        return university_chooser(request, "/faculty/register", message)

    with use_tenant(tenant):
        return faculty_register(
            request, name, employee_id, email, password, department_id
        )


def faculty_register(
    request: Request,
    name: str,
    employee_id: str,
    email: str,
    password: str,
    department_id: int,
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

    return RedirectResponse(tenant_url("/faculty/login"), status_code=303)


# ============================================================
# STUDENT REGISTRATION PAGE
# ============================================================

@app.get("/student/register", response_class=HTMLResponse)
def student_register_page(request: Request, u: str = Query("")):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)

    tenant, message = resolve_tenant(u)
    if tenant is None:
        return university_chooser(request, "/student/register", message)

    with use_tenant(tenant):
        return templates.TemplateResponse(
            request=request,
            name="student_register.html",
            context={**registration_context("student"), "university_slug": tenant.slug},
        )


# ============================================================
# STUDENT REGISTRATION
# ============================================================

@app.post("/student/register", response_class=HTMLResponse)
def student_register_route(
    request: Request,
    u: str = Query(""),
    name: str = Form(...),
    roll_number: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    department_id: int = Form(...),
    semester_id: int = Form(...),
    division_id: int = Form(...),
):
    tenant, message = resolve_tenant(u)
    if tenant is None:
        return university_chooser(request, "/student/register", message)

    with use_tenant(tenant):
        return student_register(
            request, name, roll_number, email, password,
            department_id, semester_id, division_id,
        )


def student_register(
    request: Request,
    name: str,
    roll_number: str,
    email: str,
    password: str,
    department_id: int,
    semester_id: int,
    division_id: int,
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

    return RedirectResponse(tenant_url("/student/login"), status_code=303)


# ============================================================
# FACULTY LOGIN
# ============================================================

@app.get("/faculty/login", response_class=HTMLResponse)
def faculty_login_page(request: Request, u: str = Query("")):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)

    tenant, message = resolve_tenant(u)
    if tenant is None:
        return university_chooser(request, "/faculty/login", message)

    with use_tenant(tenant):
        return login_page(request, "faculty", "Faculty")


@app.post("/faculty/login", response_class=HTMLResponse)
def faculty_login(
    request: Request,
    u: str = Query(""),
    email: str = Form(...),
    password: str = Form(...),
):
    tenant, message = resolve_tenant(u)
    if tenant is None:
        return university_chooser(request, "/faculty/login", message)

    with use_tenant(tenant):
        error = authenticate_account(request, "faculty", email, password)
        if error:
            return login_page(request, "faculty", "Faculty", error)

    return RedirectResponse("/dashboard", status_code=303)


# ============================================================
# STUDENT LOGIN
# ============================================================

@app.get("/student/login", response_class=HTMLResponse)
def student_login_page(request: Request, u: str = Query("")):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)

    tenant, message = resolve_tenant(u)
    if tenant is None:
        return university_chooser(request, "/student/login", message)

    with use_tenant(tenant):
        return login_page(request, "student", "Student")


@app.post("/student/login", response_class=HTMLResponse)
def student_login(
    request: Request,
    u: str = Query(""),
    email: str = Form(...),
    password: str = Form(...),
):
    tenant, message = resolve_tenant(u)
    if tenant is None:
        return university_chooser(request, "/student/login", message)

    with use_tenant(tenant):
        error = authenticate_account(request, "student", email, password)
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

    if current_user["role"] == "superadmin":
        return RedirectResponse("/platform/dashboard", status_code=303)

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
# UNIVERSITY REGISTRATION (public) - creates a PENDING request only
# ============================================================

@app.get("/register-university", response_class=HTMLResponse)
def university_register_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(
        request=request, name="university_register.html",
        context={"error": None, "form": {}, "submitted": False},
    )


@app.post("/register-university", response_class=HTMLResponse)
def university_register(
    request: Request,
    university_name: str = Form(...),
    address: str = Form(""),
    contact_phone: str = Form(""),
    admin_name: str = Form(...),
    admin_email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    form = {
        "university_name": university_name, "address": address,
        "contact_phone": contact_phone, "admin_name": admin_name,
        "admin_email": admin_email,
    }
    if password != confirm_password:
        error = "The two passwords do not match."
    else:
        error = platform_db.register_university(
            university_name, address, contact_phone,
            admin_name, admin_email, password,
        )

    if error:
        return templates.TemplateResponse(
            request=request, name="university_register.html",
            context={"error": error, "form": form, "submitted": False},
            status_code=400,
        )
    return templates.TemplateResponse(
        request=request, name="university_register.html",
        context={"error": None, "form": form, "submitted": True},
    )


@app.get("/register-university/status", response_class=HTMLResponse)
def university_status_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="university_status.html",
        context={"results": None, "email": ""},
    )


@app.post("/register-university/status", response_class=HTMLResponse)
def university_status(request: Request, email: str = Form(...)):
    return templates.TemplateResponse(
        request=request, name="university_status.html",
        context={
            "results": platform_db.registrations_for_email(email),
            "email": email.strip(),
        },
    )


# ============================================================
# LOGOUT
# ============================================================

@app.get("/logout")
def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/", status_code=303)