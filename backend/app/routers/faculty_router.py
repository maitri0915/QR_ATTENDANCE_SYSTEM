"""
Faculty routes — Module 3 in the module list:
Attendance session management, dynamic QR generation, live monitoring,
manual overrides, leave approval, and subject/class-wise reports.
"""
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..utils.qr import generate_qr_token
from ..utils.analytics import recalc_snapshot

router = APIRouter(
    prefix="/api/faculty",
    tags=["Faculty"],
    dependencies=[Depends(auth.require_role(models.RoleEnum.faculty))],
)


def _current_profile(current_user: models.User, db: Session) -> models.ProfileMaster:
    profile = db.query(models.ProfileMaster).filter(
        models.ProfileMaster.user_id == current_user.user_id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Faculty profile not found")
    return profile


# ---------------------------- My Classes ----------------------------
@router.get("/my-allocations", response_model=List[schemas.ClassAllocationOut])
def my_allocations(
    current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)
):
    profile = _current_profile(current_user, db)
    return db.query(models.ClassAllocation).filter(
        models.ClassAllocation.faculty_profile_id == profile.profile_id
    ).all()


# ---------------------------- Sessions ----------------------------
@router.post("/sessions", response_model=schemas.SessionOut)
def create_session(payload: schemas.SessionCreate, db: Session = Depends(get_db)):
    allocation = db.query(models.ClassAllocation).filter(
        models.ClassAllocation.allocation_id == payload.allocation_id
    ).first()
    if not allocation:
        raise HTTPException(status_code=404, detail="Class allocation not found")

    session = models.AttendanceSession(**payload.dict())  # includes classroom_latitude/longitude if provided
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


# ---------------------------- Dynamic QR ----------------------------
@router.post("/sessions/{session_id}/qr/generate", response_model=schemas.QRGenerateResponse)
def generate_qr(session_id: int, db: Session = Depends(get_db)):
    session = db.query(models.AttendanceSession).filter(
        models.AttendanceSession.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.is_closed:
        raise HTTPException(status_code=400, detail="Session is already closed")

    # Deactivate any previously issued QR for this session (time-based expiration)
    db.query(models.DynamicQRLog).filter(
        models.DynamicQRLog.session_id == session_id, models.DynamicQRLog.is_active == True  # noqa: E712
    ).update({"is_active": False})

    qr_data = generate_qr_token(session_id)
    qr_log = models.DynamicQRLog(
        session_id=session_id,
        qr_id=qr_data["qr_id"],
        qr_token_hash=qr_data["token_hash"],
        expires_at=qr_data["expires_at"],
        is_active=True,
    )
    db.add(qr_log)
    db.commit()

    return schemas.QRGenerateResponse(
        qr_id=qr_data["qr_id"],
        session_id=session_id,
        expires_at=qr_data["expires_at"],
        qr_image_base64=qr_data["image_base64"],
    )


@router.post("/sessions/{session_id}/close")
def close_session(session_id: int, db: Session = Depends(get_db)):
    session = db.query(models.AttendanceSession).filter(
        models.AttendanceSession.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.is_closed = True
    db.query(models.DynamicQRLog).filter(
        models.DynamicQRLog.session_id == session_id
    ).update({"is_active": False})
    db.commit()
    return {"detail": "Session closed"}


# ---------------------------- Live Monitoring ----------------------------
@router.get("/sessions/{session_id}/roster", response_model=List[schemas.ProfileOut])
def session_roster(session_id: int, db: Session = Depends(get_db)):
    """Students matching this session's class (semester + division) — used to populate
    the manual-override picker so faculty select a real student instead of typing an ID."""
    session = db.query(models.AttendanceSession).filter(
        models.AttendanceSession.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    allocation = db.query(models.ClassAllocation).filter(
        models.ClassAllocation.allocation_id == session.allocation_id
    ).first()

    return db.query(models.ProfileMaster).join(models.User).filter(
        models.User.role == models.RoleEnum.student,
        models.ProfileMaster.current_semester == allocation.assigned_semester,
        models.ProfileMaster.division_section == allocation.assigned_division,
    ).all()


@router.get("/sessions/{session_id}/live", response_model=List[schemas.RosterStatusOut])
def live_attendance(session_id: int, db: Session = Depends(get_db)):
    """Full class roster for this session with each student's current status —
    shows Present/Absent/Late/Not marked, not just a present-only list."""
    session = db.query(models.AttendanceSession).filter(
        models.AttendanceSession.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    allocation = db.query(models.ClassAllocation).filter(
        models.ClassAllocation.allocation_id == session.allocation_id
    ).first()

    roster = db.query(models.ProfileMaster).join(models.User).filter(
        models.User.role == models.RoleEnum.student,
        models.ProfileMaster.current_semester == allocation.assigned_semester,
        models.ProfileMaster.division_section == allocation.assigned_division,
    ).all()

    records = {
        r.student_profile_id: r
        for r in db.query(models.AttendanceRecord).filter(models.AttendanceRecord.session_id == session_id).all()
    }

    result = []
    for student in roster:
        rec = records.get(student.profile_id)
        result.append(schemas.RosterStatusOut(
            profile_id=student.profile_id,
            full_name=student.full_name,
            internal_id=student.internal_id,
            status=rec.status.value if rec else "not_marked",
            marking_method=rec.marking_method.value if rec else None,
            check_in_timestamp=rec.check_in_timestamp if rec else None,
        ))
    return result


# ---------------------------- Manual Attendance Override ----------------------------
@router.post("/sessions/{session_id}/attendance/manual", response_model=schemas.AttendanceRecordOut)
def manual_attendance(session_id: int, payload: schemas.ManualAttendanceUpdate, db: Session = Depends(get_db)):
    student = db.query(models.ProfileMaster).filter(
        models.ProfileMaster.profile_id == payload.student_profile_id
    ).first()
    if not student:
        raise HTTPException(
            status_code=404,
            detail=f"No student found with profile ID {payload.student_profile_id}. Use the student picker, not the roll number."
        )

    record = db.query(models.AttendanceRecord).filter(
        models.AttendanceRecord.session_id == session_id,
        models.AttendanceRecord.student_profile_id == payload.student_profile_id,
    ).first()

    if record:
        record.status = payload.status
        record.marking_method = models.MarkingMethodEnum.manual
    else:
        record = models.AttendanceRecord(
            session_id=session_id,
            student_profile_id=payload.student_profile_id,
            status=payload.status,
            marking_method=models.MarkingMethodEnum.manual,
            check_in_timestamp=datetime.utcnow() if payload.status != models.AttendanceStatusEnum.absent else None,
        )
        db.add(record)

    db.commit()
    db.refresh(record)

    # Keep the analytics snapshot in sync for manual marks too (previously only QR scans triggered this)
    session = db.query(models.AttendanceSession).filter(
        models.AttendanceSession.session_id == session_id
    ).first()
    if session:
        allocation = db.query(models.ClassAllocation).filter(
            models.ClassAllocation.allocation_id == session.allocation_id
        ).first()
        if allocation:
            recalc_snapshot(db, payload.student_profile_id, allocation.subject_id)

    return record


# ---------------------------- Leave Approval ----------------------------
@router.get("/leave-requests/pending", response_model=List[schemas.LeaveRequestOut])
def pending_leave_requests(db: Session = Depends(get_db)):
    return db.query(models.LeaveRequest).filter(
        models.LeaveRequest.status == models.LeaveStatusEnum.pending
    ).all()


@router.post("/leave-requests/{leave_id}/decision", response_model=schemas.LeaveRequestOut)
def decide_leave_request(
    leave_id: int, payload: schemas.LeaveDecision,
    current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db),
):
    leave = db.query(models.LeaveRequest).filter(models.LeaveRequest.leave_id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="Leave request not found")

    profile = _current_profile(current_user, db)
    leave.status = payload.status
    leave.approved_by = profile.profile_id
    db.commit()
    db.refresh(leave)
    return leave


# ---------------------------- Subject / Class-wise Reports ----------------------------
@router.get("/reports/subject/{subject_id}", response_model=List[schemas.AnalyticsSnapshotOut])
def subject_report(subject_id: int, db: Session = Depends(get_db)):
    return db.query(models.AnalyticsSnapshot).filter(
        models.AnalyticsSnapshot.subject_id == subject_id
    ).all()
