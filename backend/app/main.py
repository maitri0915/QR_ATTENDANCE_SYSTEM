"""
QR Attendance System — FastAPI entry point.
Run with:  uvicorn app.main:app --reload
"""
import os
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import models, auth
from .database import engine, SessionLocal
from .routers import auth_router, admin_router, faculty_router, student_router

# Create all tables on startup (fine for SQLite / a micro project; use Alembic for real migrations)
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="QR Attendance System",
    description="Web-based dynamic QR code attendance management system.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(faculty_router.router)
app.include_router(student_router.router)


@app.on_event("startup")
def ensure_admin_account_exists():
    """
    Auto-creates the default admin account if none exists yet.
    Means the app is usable immediately after a fresh deploy (e.g. on Render,
    where there's no easy way to run seed_admin.py by hand), and re-heals
    itself if a host's disk gets wiped on redeploy.
    """
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@college.edu")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@123")

    db = SessionLocal()
    try:
        if not db.query(models.User).filter(models.User.email == ADMIN_EMAIL).first():
            user = models.User(
                email=ADMIN_EMAIL,
                password_hash=auth.hash_password(ADMIN_PASSWORD),
                role=models.RoleEnum.admin,
            )
            db.add(user)
            db.flush()
            db.add(models.ProfileMaster(user_id=user.user_id, full_name="System Administrator", email=ADMIN_EMAIL))
            db.commit()
    finally:
        db.close()


@app.get("/api/health", tags=["Health"])
def health_check():
    return {"status": "ok"}


# Serve the static frontend (HTML/CSS/JS) directly from FastAPI so the whole
# app can run from a single process. Path is resolved relative to this file
# (not the process's working directory) so it works on any host.
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
