"""
Pydantic schemas used for request bodies and API responses.
"""
from datetime import datetime, date
from typing import Optional, List

from pydantic import BaseModel, EmailStr

from .models import RoleEnum, SessionTypeEnum, AttendanceStatusEnum, LeaveStatusEnum, MarkingMethodEnum


# ---------------------------- Auth ----------------------------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: RoleEnum
    profile_id: Optional[int] = None
    full_name: Optional[str] = None


# ---------------------------- Department ----------------------------
class DepartmentCreate(BaseModel):
    department_name: str
    description: Optional[str] = None


class DepartmentOut(BaseModel):
    department_id: int
    department_name: str
    description: Optional[str] = None

    class Config:
        from_attributes = True


# ---------------------------- Subject ----------------------------
class SubjectCreate(BaseModel):
    subject_code: str
    subject_name: str
    semester: int
    department_id: int


class SubjectOut(BaseModel):
    subject_id: int
    subject_code: str
    subject_name: str
    semester: int
    department_id: int
    total_sessions_conducted: int

    class Config:
        from_attributes = True


# ---------------------------- User / Profile ----------------------------
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: RoleEnum
    full_name: str
    phone: Optional[str] = None
    internal_id: Optional[str] = None
    department_id: Optional[int] = None
    current_semester: Optional[int] = None
    division_section: Optional[str] = None


class ProfileOut(BaseModel):
    profile_id: int
    user_id: int
    full_name: str
    email: str
    phone: Optional[str] = None
    internal_id: Optional[str] = None
    profile_pic_url: Optional[str] = None
    current_semester: Optional[int] = None
    division_section: Optional[str] = None
    department_id: Optional[int] = None

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    phone: Optional[str] = None
    profile_pic_url: Optional[str] = None
    division_section: Optional[str] = None


# ---------------------------- Class Allocation ----------------------------
class ClassAllocationCreate(BaseModel):
    subject_id: int
    faculty_profile_id: int
    assigned_semester: int
    assigned_division: str


class ClassAllocationOut(BaseModel):
    allocation_id: int
    subject_id: int
    faculty_profile_id: int
    assigned_semester: int
    assigned_division: str

    class Config:
        from_attributes = True


# ---------------------------- Attendance Session ----------------------------
class SessionCreate(BaseModel):
    allocation_id: int
    session_type: SessionTypeEnum = SessionTypeEnum.lecture
    scheduled_date: date
    start_time: datetime
    scheduled_end_time: datetime
    classroom_latitude: Optional[float] = None
    classroom_longitude: Optional[float] = None


class SessionOut(BaseModel):
    session_id: int
    allocation_id: int
    session_type: SessionTypeEnum
    scheduled_date: date
    start_time: datetime
    scheduled_end_time: datetime
    is_closed: bool
    classroom_latitude: Optional[float] = None
    classroom_longitude: Optional[float] = None

    class Config:
        from_attributes = True


# ---------------------------- Dynamic QR ----------------------------
class QRGenerateResponse(BaseModel):
    qr_id: str
    session_id: int
    expires_at: datetime
    qr_image_base64: str


class QRScanRequest(BaseModel):
    qr_id: str
    student_latitude: Optional[float] = None
    student_longitude: Optional[float] = None


# ---------------------------- Attendance Records ----------------------------
class AttendanceRecordOut(BaseModel):
    attendance_id: int
    session_id: int
    student_profile_id: int
    status: AttendanceStatusEnum
    marking_method: MarkingMethodEnum
    check_in_timestamp: Optional[datetime] = None
    check_out_timestamp: Optional[datetime] = None

    class Config:
        from_attributes = True


class ManualAttendanceUpdate(BaseModel):
    student_profile_id: int
    status: AttendanceStatusEnum


class RosterStatusOut(BaseModel):
    profile_id: int
    full_name: str
    internal_id: Optional[str] = None
    status: str  # "present" / "absent" / "late" / "not_marked"
    marking_method: Optional[str] = None
    check_in_timestamp: Optional[datetime] = None


# ---------------------------- Leave Requests ----------------------------
class LeaveRequestCreate(BaseModel):
    start_date: date
    end_date: date
    reason: str


class LeaveRequestOut(BaseModel):
    leave_id: int
    student_profile_id: int
    start_date: date
    end_date: date
    reason: str
    status: LeaveStatusEnum
    submitted_at: datetime
    approved_by: Optional[int] = None

    class Config:
        from_attributes = True


class LeaveDecision(BaseModel):
    status: LeaveStatusEnum  # approved / rejected


# ---------------------------- Analytics ----------------------------
class AnalyticsSnapshotOut(BaseModel):
    snapshot_id: int
    student_profile_id: int
    subject_id: int
    total_sessions_attended: int
    attendance_percentage: float
    is_defaulter: bool
    last_calculated_at: datetime

    class Config:
        from_attributes = True
