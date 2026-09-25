"""
Dynamic QR code generation & validation.

Each QR encodes a short-lived signed JWT (qr_id + session_id + expiry).
A hash of that token is stored in DYNAMIC_QR_LOGS so a scanned token can be
verified server-side without trusting the QR image contents alone.
"""
import base64
import hashlib
import io
import uuid
from datetime import datetime, timedelta

import qrcode
from jose import JWTError, jwt

from ..auth import SECRET_KEY, ALGORITHM

QR_VALIDITY_SECONDS = 30  # dynamic refresh window — mirrors "Time-Based QR Expiration"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_qr_token(session_id: int) -> dict:
    """Create a new signed token + matching QR image for a session."""
    qr_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(seconds=QR_VALIDITY_SECONDS)

    payload = {"session_id": session_id, "qr_id": qr_id, "exp": expires_at}
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    token_hash = _hash_token(token)

    # Build the QR image (embeds qr_id + token, scanned as JSON by the student app)
    qr_payload = f"{qr_id}|{token}"
    img = qrcode.make(qr_payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    image_base64 = base64.b64encode(buf.getvalue()).decode()

    return {
        "qr_id": qr_id,
        "token": token,
        "token_hash": token_hash,
        "expires_at": expires_at,
        "image_base64": image_base64,
    }


def verify_qr_token(token: str) -> dict:
    """Decode & validate a scanned token's signature and expiry. Raises JWTError on failure."""
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return payload
