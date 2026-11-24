"""Platform super-admin area: review university registrations and manage
university accounts. Has no access to any university's academic data."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import platform_db
from auth import get_current_user, login_user, verify_password
from templating import templates

router = APIRouter(prefix="/platform")


def _platform_user(request: Request):
    """The signed-in, still-active super admin, or None."""
    user = get_current_user(request)
    if not user or user.get("role") != "superadmin":
        return None
    admin = platform_db.get_platform_admin(user["id"])
    if not admin or admin["is_active"] != 1:
        request.session.clear()
        return None
    return user


def _flash(request: Request, message: str, kind: str = "success") -> None:
    request.session["flash"] = {"message": message, "kind": kind}


@router.get("/login", response_class=HTMLResponse)
def platform_login_page(request: Request):
    if _platform_user(request):
        return RedirectResponse("/platform/dashboard", status_code=303)
    return templates.TemplateResponse(
        request=request, name="platform_login.html", context={"error": None}
    )


@router.post("/login", response_class=HTMLResponse)
def platform_login(request: Request, email: str = Form(...), password: str = Form(...)):
    admin = platform_db.get_platform_admin_by_email(email)
    if (
        admin is None
        or admin["is_active"] != 1
        or not verify_password(password, admin["password_hash"])
    ):
        return templates.TemplateResponse(
            request=request, name="platform_login.html",
            context={"error": "Invalid email or password."}, status_code=400,
        )
    login_user(request, admin, "superadmin")
    return RedirectResponse("/platform/dashboard", status_code=303)


@router.get("/dashboard", response_class=HTMLResponse)
def platform_dashboard(request: Request):
    user = _platform_user(request)
    if not user:
        return RedirectResponse("/platform/login", status_code=303)

    universities = platform_db.list_universities()
    for uni in universities:
        uni["usage"] = (
            platform_db.tenant_usage(uni["db_path"])
            if uni["status"] in ("approved", "suspended") else None
        )

    return templates.TemplateResponse(
        request=request,
        name="platform_dashboard.html",
        context={
            "title": "Platform overview",
            "counts": platform_db.status_counts(),
            "universities": universities,
            "audit": platform_db.recent_audit(),
            "flash": request.session.pop("flash", None),
        },
    )


def _act(request, university_id, fn, success, *args):
    user = _platform_user(request)
    if not user:
        return RedirectResponse("/platform/login", status_code=303)
    error = fn(university_id, user["id"], *args)
    if error:
        _flash(request, error, "danger")
    else:
        _flash(request, success)
    return RedirectResponse("/platform/dashboard", status_code=303)


@router.post("/universities/{university_id}/approve")
def approve(request: Request, university_id: int):
    return _act(request, university_id, platform_db.approve_university,
                "University approved. Its workspace and administrator account are ready.")


@router.post("/universities/{university_id}/reject")
def reject(request: Request, university_id: int, note: str = Form("")):
    return _act(request, university_id, platform_db.reject_university,
                "Registration rejected.", note)


@router.post("/universities/{university_id}/suspend")
def suspend(request: Request, university_id: int, note: str = Form("")):
    return _act(request, university_id, platform_db.suspend_university,
                "University suspended. Its users are signed out and cannot sign in.", note)


@router.post("/universities/{university_id}/activate")
def activate(request: Request, university_id: int):
    return _act(request, university_id, platform_db.activate_university,
                "University re-activated.")
