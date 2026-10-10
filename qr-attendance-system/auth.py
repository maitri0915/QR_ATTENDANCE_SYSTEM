
from typing import Optional

from fastapi import HTTPException, Request
from pwdlib import PasswordHash


password_hash = PasswordHash.recommended()

VALID_ROLES = {"admin", "faculty", "student"}


def hash_password(password: str) -> str:
    """Hash a plain-text password securely."""
    if not isinstance(password, str) or not password:
        raise ValueError("Password cannot be empty.")

    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against its stored hash."""
    if not isinstance(password, str) or not isinstance(stored_hash, str):
        return False

    if not password or not stored_hash:
        return False

    try:
        return password_hash.verify(password, stored_hash)
    except (ValueError, TypeError):
        # Invalid or malformed stored hashes must not crash login.
        return False


def get_current_user(request: Request) -> Optional[dict]:
    """
    Return the authenticated account stored in the session.

    Returns None when the session is missing or invalid.
    """
    account = request.session.get("user")

    if not isinstance(account, dict):
        return None

    if account.get("role") not in VALID_ROLES:
        return None

    if not isinstance(account.get("id"), int):
        return None

    if account["id"] <= 0:
        return None

    if not isinstance(account.get("name"), str):
        return None

    if not isinstance(account.get("email"), str):
        return None

    return account


def login_user(request: Request, account: dict, role: str) -> None:
    """
    Store a successfully authenticated account in the session.

    The caller must verify the password against the correct database
    table before calling this function.
    """
    if role not in VALID_ROLES:
        raise ValueError("Invalid account role.")

    if not isinstance(account, dict):
        raise ValueError("Invalid account information.")

    account_id = account.get("id")
    name = account.get("name")
    email = account.get("email")

    if not isinstance(account_id, int) or account_id <= 0:
        raise ValueError("Invalid account ID.")

    if not isinstance(name, str) or not name.strip():
        raise ValueError("Invalid account name.")

    if not isinstance(email, str) or not email.strip():
        raise ValueError("Invalid account email.")

    # Reject accounts explicitly marked as inactive.
    if account.get("is_active", 1) != 1:
        raise ValueError("This account is inactive.")

    # Clear previous session data before starting a new session.
    request.session.clear()

    request.session["user"] = {
        "id": account_id,
        "name": name,
        "email": email,
        "role": role,
    }


def logout_user(request: Request) -> None:
    """Clear the current session."""
    request.session.clear()


def require_authenticated_user(request: Request) -> dict:
    """
    Require a valid login.

    Suitable for direct checks inside route functions.
    """
    account = get_current_user(request)

    if account is None:
        raise HTTPException(
            status_code=401,
            detail="Please log in to continue.",
        )

    return account


def require_role(role: str):
    """
    Create a FastAPI dependency that requires a specific role.

    Example:
        current_user: dict = Depends(require_role("faculty"))
    """
    if role not in VALID_ROLES:
        raise ValueError("Invalid account role.")

    def role_dependency(request: Request) -> dict:
        account = require_authenticated_user(request)

        if account["role"] != role:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to access this resource.",
            )

        return account

    return role_dependency


def require_any_role(*roles: str):
    """
    Create a dependency that permits any of the specified roles.

    Example:
        current_user: dict = Depends(
            require_any_role("admin", "faculty")
        )
    """
    if not roles or any(role not in VALID_ROLES for role in roles):
        raise ValueError("One or more account roles are invalid.")

    allowed_roles = set(roles)

    def role_dependency(request: Request) -> dict:
        account = require_authenticated_user(request)

        if account["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to access this resource.",
            )

        return account

    return role_dependency