"""
ORM models — one class per entity in the ER diagram.
Entities: USERS, DEPARTMENTS, SUBJECTS, PROFILE_MASTER, CLASS_ALLOCATION,
ATTENDANCE_SESSIONS, ATTENDANCE_RECORDS, DYNAMIC_QR_LOGS, LEAVE_REQUEST,
ANALYTICS_SNAPSHOTS.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Date, Time,
    ForeignKey, Enum, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship

from .database import Base


class RoleEnum(str, enum.Enum):
    admin = "admin"
    faculty = "faculty"
    student = "student"


class SessionTypeEnum(str, enum.Enum):
    lecture = "lecture"
    practical = "practical"


class AttendanceStatusEnum(str, enum.Enum):
    present = "present"
    absent = "absent"
    late = "late"


class LeaveStatusEnum(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class MarkingMethodEnum(str, enum.Enum):
    qr = "qr"
    manual = "manual"


# ---------------------------------------------------------------------------
# USERS
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(Enum(RoleEnum), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    profile = relationship("ProfileMaster", back_populates="user", uselist=False)


# ---------------------------------------------------------------------------
# DEPARTMENTS
# ---------------------------------------------------------------------------
class Department(Base):
    __tablename__ = "departments"

    department_id = Column(Integer, primary_key=True, index=True)
    department_name = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=True)

    subjects = relationship("Subject", back_populates="department")
    profiles = relationship("ProfileMaster", back_populates="department")


# ---------------------------------------------------------------------------
# SUBJECTS
# ---------------------------------------------------------------------------
class Subject(Base):
    __tablename__ = "subjects"

    subject_id = Column(Integer, primary_key=True, index=True)
    subject_code = Column(String, unique=True, nullable=False)
    subject_name = Column(String, nullable=False)
    semester = Column(Integer, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=False)
    total_sessions_conducted = Column(Integer, default=0)

    department = relationship("Department", back_populates="subjects")
    allocations = relationship("ClassAllocation", back_populates="subject")
    analytics_snapshots = relationship("AnalyticsSnapshot", back_populates="subject")


# ---------------------------------------------------------------------------
# PROFILE_MASTER
# ---------------------------------------------------------------------------
class ProfileMaster(Base):
    __tablename__ = "profile_master"

    profile_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), unique=True, nullable=False)
    full_name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    internal_id = Column(String, nullable=True)  # Roll number / Employee ID
    profile_pic_url = Column(String, nullable=True)
    current_semester = Column(Integer, nullable=True)
    division_section = Column(String, nullable=True)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=True)

    user = relationship("User", back_populates="profile")
    department = relationship("Department", back_populates="profiles")

    taught_allocations = relationship(
        "ClassAllocation", back_populates="faculty", foreign_keys="ClassAllocation.faculty_profile_id"
    )
    attendance_records = relationship(
        "AttendanceRecord", back_populates="student", foreign_keys="AttendanceRecord.student_profile_id"
    )
    leave_requests = relationship(
        "LeaveRequest", back_populates="student", foreign_keys="LeaveRequest.student_profile_id"
    )
    analytics_snapshots = relationship("AnalyticsSnapshot", back_populates="student")


# ---------------------------------------------------------------------------
# CLASS_ALLOCATION
# ---------------------------------------------------------------------------
class ClassAllocation(Base):
    __tablename__ = "class_allocation"

    allocation_id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.subject_id"), nullable=False)
    faculty_profile_id = Column(Integer, ForeignKey("profile_master.profile_id"), nullable=False)
    assigned_semester = Column(Integer, nullable=False)
    assigned_division = Column(String, nullable=False)

    subject = relationship("Subject", back_populates="allocations")
    faculty = relationship(
        "ProfileMaster", back_populates="taught_allocations", foreign_keys=[faculty_profile_id]
    )
    sessions = relationship("AttendanceSession", back_populates="allocation")


# ---------------------------------------------------------------------------
# ATTENDANCE_SESSIONS
# ---------------------------------------------------------------------------
class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"

    session_id = Column(Integer, primary_key=True, index=True)
    allocation_id = Column(Integer, ForeignKey("class_allocation.allocation_id"), nullable=False)
    session_type = Column(Enum(SessionTypeEnum), default=SessionTypeEnum.lecture)
    scheduled_date = Column(Date, nullable=False)
    start_time = Column(DateTime, nullable=False)
    scheduled_end_time = Column(DateTime, nullable=False)
    is_closed = Column(Boolean, default=False)
    classroom_latitude = Column(Float, nullable=True)
    classroom_longitude = Column(Float, nullable=True)

    allocation = relationship("ClassAllocation", back_populates="sessions")
    records = relationship("AttendanceRecord", back_populates="session")
    qr_logs = relationship("DynamicQRLog", back_populates="session")


# ---------------------------------------------------------------------------
# DYNAMIC_QR_LOGS
# ---------------------------------------------------------------------------
class DynamicQRLog(Base):
    __tablename__ = "dynamic_qr_logs"

    qr_log_id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("attendance_sessions.session_id"), nullable=False)
    qr_id = Column(String, unique=True, index=True, nullable=False)  # public identifier embedded in QR
    qr_token_hash = Column(String, nullable=False)  # hash of the signed token, for validation
    generated_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)

    session = relationship("AttendanceSession", back_populates="qr_logs")


# ---------------------------------------------------------------------------
# ATTENDANCE_RECORDS
# ---------------------------------------------------------------------------
class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("session_id", "student_profile_id", name="uq_session_student"),)

    attendance_id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("attendance_sessions.session_id"), nullable=False)
    student_profile_id = Column(Integer, ForeignKey("profile_master.profile_id"), nullable=False)
    status = Column(Enum(AttendanceStatusEnum), default=AttendanceStatusEnum.absent)
    marking_method = Column(Enum(MarkingMethodEnum), default=MarkingMethodEnum.qr)
    check_in_timestamp = Column(DateTime, nullable=True)
    check_out_timestamp = Column(DateTime, nullable=True)

    session = relationship("AttendanceSession", back_populates="records")
    student = relationship(
        "ProfileMaster", back_populates="attendance_records", foreign_keys=[student_profile_id]
    )


# ---------------------------------------------------------------------------
# LEAVE_REQUEST
# ---------------------------------------------------------------------------
class LeaveRequest(Base):
    __tablename__ = "leave_request"

    leave_id = Column(Integer, primary_key=True, index=True)
    student_profile_id = Column(Integer, ForeignKey("profile_master.profile_id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(Enum(LeaveStatusEnum), default=LeaveStatusEnum.pending)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    approved_by = Column(Integer, ForeignKey("profile_master.profile_id"), nullable=True)

    student = relationship(
        "ProfileMaster", back_populates="leave_requests", foreign_keys=[student_profile_id]
    )
    approver = relationship("ProfileMaster", foreign_keys=[approved_by])


# ---------------------------------------------------------------------------
# ANALYTICS_SNAPSHOTS
# ---------------------------------------------------------------------------
class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"
    __table_args__ = (UniqueConstraint("student_profile_id", "subject_id", name="uq_student_subject_snapshot"),)

    snapshot_id = Column(Integer, primary_key=True, index=True)
    student_profile_id = Column(Integer, ForeignKey("profile_master.profile_id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.subject_id"), nullable=False)
    total_sessions_attended = Column(Integer, default=0)
    attendance_percentage = Column(Float, default=0.0)
    is_defaulter = Column(Boolean, default=False)
    last_calculated_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("ProfileMaster", back_populates="analytics_snapshots")
    subject = relationship("Subject", back_populates="analytics_snapshots")
