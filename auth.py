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
    Get the currently authenticated user from the session.

    Returns:
        User dictionary if logged in.
        None if not logged in.
    """

    user = request.session.get("user")

    if not user:
        return None

    return user


def login_user(request: Request, user: dict) -> None:
    """
    Store only the necessary user information in the session.
    """

    request.session.clear()

    request.session["user"] = {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
    }


def logout_user(request: Request) -> None:
    """
    Remove the current session.
    """

    request.session.clear()