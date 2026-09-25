"""
Student routes — Module 4 in the module list:
QR scanning, attendance history & percentage, leave management, profile.
"""
import hashlib
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from jose import JWTError
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..utils.qr import verify_qr_token
from ..utils.analytics import recalc_snapshot
from ..utils.geolocation import distance_meters, DEFAULT_MAX_DISTANCE_METERS

router = APIRouter(
    prefix="/api/student",
    tags=["Student"],
    dependencies=[Depends(auth.require_role(models.RoleEnum.student))],
)


def _current_profile(current_user: models.User, db: Session) -> models.ProfileMaster:
    profile = db.query(models.ProfileMaster).filter(
        models.ProfileMaster.user_id == current_user.user_id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Student profile not found")
    return profile


# ---------------------------- QR Scan / Mark Attendance ----------------------------
@router.post("/attendance/scan", response_model=schemas.AttendanceRecordOut)
def scan_qr(
    payload: schemas.QRScanRequest,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    profile = _current_profile(current_user, db)

    # 1. Verify signature & expiry of the scanned token
    try:
        token_payload = verify_qr_token(payload.token)
    except JWTError:
        raise HTTPException(status_code=400, detail="QR code is invalid or has expired")

    if token_payload.get("qr_id") != payload.qr_id:
        raise HTTPException(status_code=400, detail="QR code mismatch")

    # 2. Look up the matching log entry and re-validate against the DB
    qr_log = db.query(models.DynamicQRLog).filter(
        models.DynamicQRLog.qr_id == payload.qr_id
    ).first()
    if not qr_log or not qr_log.is_active:
        raise HTTPException(status_code=400, detail="This QR code is no longer active")
    if qr_log.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="QR code has expired — ask faculty to refresh it")

    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    if token_hash != qr_log.qr_token_hash:
        raise HTTPException(status_code=400, detail="QR code validation failed")

    session_id = qr_log.session_id
    session = db.query(models.AttendanceSession).filter(
        models.AttendanceSession.session_id == session_id
    ).first()
    if not session or session.is_closed:
        raise HTTPException(status_code=400, detail="This attendance session is closed")

    # 3. Geolocation check — reject if the student's device is too far from the
    # classroom (mitigates handing an unlocked phone to a friend elsewhere).
    if session.classroom_latitude is not None and session.classroom_longitude is not None:
        if payload.student_latitude is None or payload.student_longitude is None:
            raise HTTPException(
                status_code=400,
                detail="Location access is required to mark attendance for this session. Please allow location and try again."
            )
        dist = distance_meters(
            session.classroom_latitude, session.classroom_longitude,
            payload.student_latitude, payload.student_longitude,
        )
        if dist > DEFAULT_MAX_DISTANCE_METERS:
            raise HTTPException(
                status_code=400,
                detail=f"You appear to be too far from the classroom ({int(dist)}m away) to mark attendance from this location."
            )

    # 4. Record / update attendance
    record = db.query(models.AttendanceRecord).filter(
        models.AttendanceRecord.session_id == session_id,
        models.AttendanceRecord.student_profile_id == profile.profile_id,
    ).first()

    if record and record.status == models.AttendanceStatusEnum.present:
        raise HTTPException(status_code=400, detail="Attendance already marked for this session")

    if record:
        record.status = models.AttendanceStatusEnum.present
        record.marking_method = models.MarkingMethodEnum.qr
        record.check_in_timestamp = datetime.utcnow()
    else:
        record = models.AttendanceRecord(
            session_id=session_id,
            student_profile_id=profile.profile_id,
            status=models.AttendanceStatusEnum.present,
            marking_method=models.MarkingMethodEnum.qr,
            check_in_timestamp=datetime.utcnow(),
        )
        db.add(record)

    db.commit()
    db.refresh(record)

    # 5. Refresh analytics snapshot for this subject
    allocation = db.query(models.ClassAllocation).filter(
        models.ClassAllocation.allocation_id == session.allocation_id
    ).first()
    if allocation:
        recalc_snapshot(db, profile.profile_id, allocation.subject_id)

    return record


# ---------------------------- Attendance History ----------------------------
@router.get("/attendance/history", response_model=List[schemas.AttendanceRecordOut])
def attendance_history(
    current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)
):
    profile = _current_profile(current_user, db)
    return db.query(models.AttendanceRecord).filter(
        models.AttendanceRecord.student_profile_id == profile.profile_id
    ).all()


# ---------------------------- Attendance Percentage / Defaulter ----------------------------
@router.get("/attendance/analytics", response_model=List[schemas.AnalyticsSnapshotOut])
def attendance_analytics(
    current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)
):
    profile = _current_profile(current_user, db)
    return db.query(models.AnalyticsSnapshot).filter(
        models.AnalyticsSnapshot.student_profile_id == profile.profile_id
    ).all()


# ---------------------------- Leave Requests ----------------------------
@router.post("/leave-requests", response_model=schemas.LeaveRequestOut)
def submit_leave(
    payload: schemas.LeaveRequestCreate,
    current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db),
):
    profile = _current_profile(current_user, db)
    leave = models.LeaveRequest(student_profile_id=profile.profile_id, **payload.dict())
    db.add(leave)
    db.commit()
    db.refresh(leave)
    return leave


@router.get("/leave-requests/mine", response_model=List[schemas.LeaveRequestOut])
def my_leave_requests(
    current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)
):
    profile = _current_profile(current_user, db)
    return db.query(models.LeaveRequest).filter(
        models.LeaveRequest.student_profile_id == profile.profile_id
    ).all()


# ---------------------------- Profile ----------------------------
@router.put("/profile", response_model=schemas.ProfileOut)
def update_profile(
    payload: schemas.ProfileUpdate,
    current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db),
):
    profile = _current_profile(current_user, db)
    for field, value in payload.dict(exclude_unset=True).items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile
