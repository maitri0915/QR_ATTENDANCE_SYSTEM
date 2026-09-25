# QR Attendance System

A web-based attendance management system built around dynamic, time-limited QR codes.
Backend: **FastAPI + SQLite (SQLAlchemy)**. Frontend: plain **HTML/CSS/JS** (no build step).

Matches the ER diagram / DFD / module list: role-based dashboards for **Administrator**,
**Faculty**, and **Student**, dynamic QR generation & validation, leave management,
attendance analytics, and CSV/Excel report export.

## Project structure

```
qr-attendance-system/
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app, mounts frontend + routers
│   │   ├── database.py       # SQLAlchemy engine/session
│   │   ├── models.py         # ORM models (matches the ER diagram)
│   │   ├── schemas.py        # Pydantic request/response models
│   │   ├── auth.py           # JWT auth, password hashing, role guard
│   │   ├── utils/
│   │   │   ├── qr.py         # Dynamic QR generation & token verification
│   │   │   └── analytics.py  # Attendance % + defaulter recalculation
│   │   └── routers/
│   │       ├── auth_router.py
│   │       ├── admin_router.py
│   │       ├── faculty_router.py
│   │       └── student_router.py
│   ├── seed_admin.py         # Creates the first admin account
│   └── requirements.txt
└── frontend/
    ├── index.html             # Redirects to login or the right dashboard
    ├── login.html
    ├── admin.html
    ├── faculty.html
    ├── student.html
    ├── css/style.css
    └── js/
        ├── api.js             # Shared fetch wrapper + session/auth helpers
        ├── admin.js
        ├── faculty.js
        └── student.js
```

## Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Creates the first administrator account (admin@college.edu / Admin@123)
python seed_admin.py

# Run the app (serves both the API and the frontend)
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000** in your browser and log in with:
- Email: `admin@college.edu`
- Password: `Admin@123`

> Change `ADMIN_EMAIL` / `ADMIN_PASSWORD` at the top of `seed_admin.py` before running it
> if you want different credentials, and change `SECRET_KEY` in `app/auth.py` before any
> real deployment.

## Typical flow to try it out

1. **Log in as admin** → create a Department → create a Subject → create a Faculty
   account and a Student account → assign the subject to the faculty under
   **Class Allocation**.
2. **Log out, log in as that faculty** → go to **Start a Session** → pick the class →
   **Create session & show QR**. A QR code appears and auto-refreshes every 30 seconds.
3. **Log in as the student on a second device/browser** (or your phone, if running on
   your LAN IP) → **Scan QR** → allow camera access → point it at the faculty's screen.
   Attendance is marked instantly and the faculty's "Live roll call" updates.
4. Check **My Attendance** on the student side for the attendance percentage and
   defaulter flag (< 75% attendance), or **Reports** on the admin side to export a
   CSV/Excel of everything.

## How the dynamic QR works

1. Faculty starts a session → `POST /api/faculty/sessions`.
2. Faculty requests a QR → `POST /api/faculty/sessions/{id}/qr/generate` creates a
   signed, short-lived JWT (30s) containing the session ID, embeds it in a QR image,
   and stores a **hash** of the token (never the raw token) in `dynamic_qr_logs`.
3. The frontend re-requests a fresh QR every 30 seconds automatically, so a
   screenshotted/shared QR stops working almost immediately (Module 5: Time-Based QR
   Expiration).
4. Student scans → the browser decodes the QR locally (jsQR) and calls
   `POST /api/student/attendance/scan` with the token. The backend verifies the JWT
   signature + expiry + matching hash before marking the student present, which
   prevents proxy attendance from a copied/forwarded image.

## Notes on scope

This is a working full-stack scaffold covering every module in the module list end to
end (auth, admin CRUD, faculty sessions/QR/leave approval, student scan/history/leave,
analytics, CSV/Excel export). A few things you may want to extend for a production
version: email verification on account creation, password reset, WebSocket-based live
roll call (currently polls every 4s), and stricter enrolment checks (currently any
logged-in student can scan any session's QR — you may want to also validate that the
student's semester/division matches the session's class before marking them present).
