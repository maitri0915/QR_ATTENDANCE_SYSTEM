"""
Administrator routes — Module 2 in the module list:
Department / Student / Faculty / Academic management, attendance monitoring,
and report export.
"""
import io
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(
    prefix="/api/admin",
    tags=["Administrator"],
    dependencies=[Depends(auth.require_role(models.RoleEnum.admin))],
)


# ---------------------------- Departments ----------------------------
@router.post("/departments", response_model=schemas.DepartmentOut)
def create_department(payload: schemas.DepartmentCreate, db: Session = Depends(get_db)):
    if db.query(models.Department).filter(models.Department.department_name == payload.department_name).first():
        raise HTTPException(status_code=400, detail="Department already exists")
    dept = models.Department(**payload.dict())
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return dept


@router.get("/departments", response_model=List[schemas.DepartmentOut])
def list_departments(db: Session = Depends(get_db)):
    return db.query(models.Department).all()


# ---------------------------- Subjects ----------------------------
@router.post("/subjects", response_model=schemas.SubjectOut)
def create_subject(payload: schemas.SubjectCreate, db: Session = Depends(get_db)):
    if db.query(models.Subject).filter(models.Subject.subject_code == payload.subject_code).first():
        raise HTTPException(status_code=400, detail="Subject code already exists")
    subject = models.Subject(**payload.dict())
    db.add(subject)
    db.commit()
    db.refresh(subject)
    return subject


@router.get("/subjects", response_model=List[schemas.SubjectOut])
def list_subjects(department_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(models.Subject)
    if department_id:
        q = q.filter(models.Subject.department_id == department_id)
    return q.all()


# ---------------------------- Users (Students / Faculty / Admins) ----------------------------
@router.post("/users", response_model=schemas.ProfileOut)
def create_user(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = models.User(
        email=payload.email,
        password_hash=auth.hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.flush()  # get user.user_id without committing yet

    profile = models.ProfileMaster(
        user_id=user.user_id,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        internal_id=payload.internal_id,
        department_id=payload.department_id,
        current_semester=payload.current_semester,
        division_section=payload.division_section,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/users", response_model=List[schemas.ProfileOut])
def list_users(role: Optional[models.RoleEnum] = None, db: Session = Depends(get_db)):
    q = db.query(models.ProfileMaster).join(models.User)
    if role:
        q = q.filter(models.User.role == role)
    return q.all()


@router.delete("/users/{profile_id}")
def delete_user(profile_id: int, db: Session = Depends(get_db)):
    profile = db.query(models.ProfileMaster).filter(models.ProfileMaster.profile_id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    user = db.query(models.User).filter(models.User.user_id == profile.user_id).first()
    db.delete(profile)
    if user:
        db.delete(user)
    db.commit()
    return {"detail": "User removed"}


# ---------------------------- Class Allocation ----------------------------
@router.post("/class-allocations", response_model=schemas.ClassAllocationOut)
def create_allocation(payload: schemas.ClassAllocationCreate, db: Session = Depends(get_db)):
    allocation = models.ClassAllocation(**payload.dict())
    db.add(allocation)
    db.commit()
    db.refresh(allocation)
    return allocation


@router.get("/class-allocations", response_model=List[schemas.ClassAllocationOut])
def list_allocations(db: Session = Depends(get_db)):
    return db.query(models.ClassAllocation).all()


# ---------------------------- Attendance Monitoring ----------------------------
@router.get("/attendance/overview")
def attendance_overview(
    department_id: Optional[int] = None,
    semester: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = (
        db.query(models.AttendanceRecord, models.AttendanceSession, models.ClassAllocation, models.Subject)
        .join(models.AttendanceSession, models.AttendanceRecord.session_id == models.AttendanceSession.session_id)
        .join(models.ClassAllocation, models.AttendanceSession.allocation_id == models.ClassAllocation.allocation_id)
        .join(models.Subject, models.ClassAllocation.subject_id == models.Subject.subject_id)
    )
    if department_id:
        q = q.filter(models.Subject.department_id == department_id)
    if semester:
        q = q.filter(models.ClassAllocation.assigned_semester == semester)

    results = []
    for record, session, allocation, subject in q.all():
        results.append({
            "attendance_id": record.attendance_id,
            "student_profile_id": record.student_profile_id,
            "status": record.status.value,
            "subject_name": subject.subject_name,
            "division": allocation.assigned_division,
            "scheduled_date": session.scheduled_date.isoformat(),
        })
    return results


# ---------------------------- Report Export (CSV / Excel) ----------------------------
@router.get("/reports/export")
def export_report(format: str = "csv", db: Session = Depends(get_db)):
    rows = attendance_overview(db=db)
    if not rows:
        raise HTTPException(status_code=404, detail="No attendance data to export")

    df = pd.DataFrame(rows)
    buf = io.BytesIO()

    if format == "xlsx":
        df.to_excel(buf, index=False, engine="openpyxl")
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "attendance_report.xlsx"
    else:
        df.to_csv(buf, index=False)
        media_type = "text/csv"
        filename = "attendance_report.csv"

    buf.seek(0)
    return StreamingResponse(
        buf, media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
