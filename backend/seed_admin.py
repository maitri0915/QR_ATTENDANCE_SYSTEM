"""
Run once to create the first Administrator account:
    python seed_admin.py
"""
from app.database import SessionLocal, engine
from app import models, auth

models.Base.metadata.create_all(bind=engine)

db = SessionLocal()

ADMIN_EMAIL = "admin@college.edu"
ADMIN_PASSWORD = "Admin@123"

existing = db.query(models.User).filter(models.User.email == ADMIN_EMAIL).first()
if existing:
    print(f"Admin already exists: {ADMIN_EMAIL}")
else:
    user = models.User(
        email=ADMIN_EMAIL,
        password_hash=auth.hash_password(ADMIN_PASSWORD),
        role=models.RoleEnum.admin,
    )
    db.add(user)
    db.flush()

    profile = models.ProfileMaster(
        user_id=user.user_id,
        full_name="System Administrator",
        email=ADMIN_EMAIL,
    )
    db.add(profile)
    db.commit()
    print(f"Created admin account -> email: {ADMIN_EMAIL}  password: {ADMIN_PASSWORD}")

db.close()
