"""
Auth routes — login and "who am I".
User accounts themselves are created by the Administrator (see admin_router),
matching the DFD: Administrator -> "Submit New User Registration Details".
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/login", response_model=schemas.TokenResponse)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not auth.verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token = auth.create_access_token({"sub": str(user.user_id), "role": user.role.value})
    profile = user.profile

    return schemas.TokenResponse(
        access_token=token,
        role=user.role,
        profile_id=profile.profile_id if profile else None,
        full_name=profile.full_name if profile else None,
    )


@router.get("/me", response_model=schemas.ProfileOut)
def get_me(current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    profile = db.query(models.ProfileMaster).filter(
        models.ProfileMaster.user_id == current_user.user_id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile
