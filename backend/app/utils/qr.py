"""
Dynamic QR code generation & validation.

The QR image encodes ONLY the short qr_id (a UUID) — deliberately kept small
so the printed/displayed QR stays low-density and easy for a phone camera to
resolve. The database row (DYNAMIC_QR_LOGS) is the source of truth for
validity: is_active + expires_at are checked server-side on scan, so nothing
sensitive needs to travel inside the QR image itself.

A random per-QR secret is still generated and its hash stored in
qr_token_hash (matching the ER diagram's attribute) — this is kept
server-side only and isn't required for scan validation, but preserves a
verifiable secret per QR for any future stricter validation needs.
"""
import base64
import hashlib
import io
import uuid
from datetime import datetime, timedelta

import qrcode

QR_VALIDITY_SECONDS = 30  # dynamic refresh window — mirrors "Time-Based QR Expiration"


def generate_qr_token(session_id: int) -> dict:
    """Create a new QR log entry + a compact, easy-to-scan QR image for a session."""
    qr_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(seconds=QR_VALIDITY_SECONDS)

    # Random secret, hashed and stored server-side only — never encoded in the QR.
    secret = str(uuid.uuid4())
    token_hash = hashlib.sha256(secret.encode()).hexdigest()

    # QR encodes ONLY the short qr_id — keeps the pattern low-density and scannable.
    img = qrcode.make(qr_id, box_size=10, border=4)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    image_base64 = base64.b64encode(buf.getvalue()).decode()

    return {
        "qr_id": qr_id,
        "token_hash": token_hash,
        "expires_at": expires_at,
        "image_base64": image_base64,
    }
