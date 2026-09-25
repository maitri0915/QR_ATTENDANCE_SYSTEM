"""
Recomputes an ANALYTICS_SNAPSHOTS row for a given student + subject.
Called after every attendance mark (QR or manual) — Module 6: Attendance
Percentage Calculation & Defaulter Identification.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from .. import models

DEFAULTER_THRESHOLD_PERCENT = 75.0


def recalc_snapshot(db: Session, student_profile_id: int, subject_id: int) -> models.AnalyticsSnapshot:
    total_sessions = (
        db.query(models.AttendanceSession)
        .join(models.ClassAllocation, models.AttendanceSession.allocation_id == models.ClassAllocation.allocation_id)
        .filter(models.ClassAllocation.subject_id == subject_id)
        .count()
    )

    attended = (
        db.query(models.AttendanceRecord)
        .join(models.AttendanceSession, models.AttendanceRecord.session_id == models.AttendanceSession.session_id)
        .join(models.ClassAllocation, models.AttendanceSession.allocation_id == models.ClassAllocation.allocation_id)
        .filter(
            models.ClassAllocation.subject_id == subject_id,
            models.AttendanceRecord.student_profile_id == student_profile_id,
            models.AttendanceRecord.status == models.AttendanceStatusEnum.present,
        )
        .count()
    )

    percentage = (attended / total_sessions * 100) if total_sessions else 0.0

    snapshot = db.query(models.AnalyticsSnapshot).filter(
        models.AnalyticsSnapshot.student_profile_id == student_profile_id,
        models.AnalyticsSnapshot.subject_id == subject_id,
    ).first()

    if not snapshot:
        snapshot = models.AnalyticsSnapshot(student_profile_id=student_profile_id, subject_id=subject_id)
        db.add(snapshot)

    snapshot.total_sessions_attended = attended
    snapshot.attendance_percentage = round(percentage, 2)
    snapshot.is_defaulter = percentage < DEFAULTER_THRESHOLD_PERCENT
    snapshot.last_calculated_at = datetime.utcnow()

    db.commit()
    db.refresh(snapshot)
    return snapshot
