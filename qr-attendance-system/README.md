# AttendEase – QR Attendance System

Web-based attendance for colleges. Faculty show a QR code that changes every 30 seconds; students scan it on their phones.
Attendance is accepted only when the student belongs to the class **and is physically on campus** (checked by the server – students never see or enter coordinates).

**Stack:** FastAPI · SQLite · Jinja2 templates · Bootstrap (bundled locally, no CDN needed).

## Features
- **Admin** – departments, semesters, divisions, subjects, timetable, faculty/student lists, one-click **Campus location** setup
- **Faculty** – start a session for today's lecture, live QR + roll call, close session, approve/reject leave, timetable
- **Student** – scan QR, attendance percentage per subject, leave requests, timetable
- Short-lived random QR tokens (only a hash is stored), duplicate/proxy protection, class membership check, GPS radius check

## Quick start

```bash
python -m venv venv
venv\Scripts\activate            # Windows   (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt

cp .env.example .env             # then edit college name, admin login, etc.
python init_db.py                # creates data/attendance.db and the first admin
uvicorn main:app --reload
```
Or run `run.bat` (Windows) / `./run.sh` (Linux/macOS). Open http://127.0.0.1:8000.

Add `--demo` to `python init_db.py` to also create a sample department, semesters and subjects.

## Setting up for your college
1. Edit `.env`: `COLLEGE_NAME`, `APP_NAME`, `SUPPORT_EMAIL`, admin email/password.
2. Sign in at **/admin/login**.
3. **Campus** → stand on campus, press **Use my current location**, choose the allowed distance (100–200 m is typical). The page only shows "Campus location is set" and a map – no raw coordinates.
4. **Management** → add departments, semesters, divisions, subjects, then timetable entries (class + subject + faculty + day + time).
5. Faculty and students register themselves from the home page; share the site address with them.

## Deploying
- Run behind HTTPS (phone camera and GPS require it) – e.g. Nginx/Caddy in front of `uvicorn main:app --host 127.0.0.1 --port 8000`.
- Set `COOKIE_HTTPS_ONLY=1` and a strong `SESSION_SECRET_KEY` in `.env` (a key is auto-generated in `data/secret_key` if you don't).
- Back up the `data/` folder – it holds the database.
- No internet access is needed by the app itself (fonts, icons, QR scanner are bundled); the Campus page map preview uses OpenStreetMap when online.

## Daily use
Faculty open the session during the lecture time (the server only allows it between the timetable start and end) → QR appears → students scan → faculty closes the session. Students can see percentages and request leave for future lectures.

## Files
`main.py` app & login/registration · `admin.py` `faculty.py` `student.py` role routes · `config.py` settings from `.env` · `database.py` schema · `init_db.py` first-run setup · `templates/` `static/` UI.
