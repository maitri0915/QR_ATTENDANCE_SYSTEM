from typing import Optional

from fastapi import Request
from pwdlib import PasswordHash


password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """
    Convert a plain password into a secure Argon2 hash.
    """
    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """
    Verify a plain password against its stored hash.
    """
    return password_hash.verify(password, stored_hash)


def get_current_user(request: Request) -> Optional[dict]:
    """
    Get the currently authenticated account from the session.

    The session can contain an admin, faculty, or student account.

    Returns:
        Account dictionary if logged in.
        None if not logged in.
    """

    account = request.session.get("user")

    if not account:
        return None

    return account


def login_user(request: Request, account: dict, role: str) -> None:
    """
    Store the authenticated account in the session.

    role must be:
        admin
        faculty
        student
    """

    if role not in ("admin", "faculty", "student"):
        raise ValueError("Invalid account role.")

    request.session.clear()

    request.session["user"] = {
        "id": account["id"],
        "name": account["name"],
        "email": account["email"],
        "role": role,
    }


def logout_user(request: Request) -> None:
    """
    Remove the current session.
    """

    request.session.clear()