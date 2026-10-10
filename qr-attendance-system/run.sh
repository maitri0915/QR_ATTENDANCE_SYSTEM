#!/usr/bin/env bash
set -e
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
[ -f data/attendance.db ] || python init_db.py
uvicorn main:app --reload
