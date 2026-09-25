"""
QR Attendance System — FastAPI entry point.
Run with:  uvicorn app.main:app --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import models
from .database import engine
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


@app.get("/api/health", tags=["Health"])
def health_check():
    return {"status": "ok"}


# Serve the static frontend (HTML/CSS/JS) directly from FastAPI so the whole
# app can run from a single process during development / demo.
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
