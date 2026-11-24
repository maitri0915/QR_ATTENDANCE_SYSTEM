"""Turso management API: creates / deletes the per-university databases.

Needs TURSO_API_TOKEN (an account-level "platform API" token) and TURSO_ORG.
Database queries themselves use TURSO_AUTH_TOKEN (see turso_client.py)."""

import json
import urllib.error
import urllib.request

import config

API = "https://api.turso.tech"


class TursoAdminError(RuntimeError):
    pass


def _require():
    if not config.TURSO_API_TOKEN or not config.TURSO_ORG:
        raise TursoAdminError(
            "Creating a university database needs TURSO_API_TOKEN and TURSO_ORG "
            "to be set in the environment."
        )


def _call(method, path, body=None, query=""):
    _require()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}{query}", data=data, method=method,
        headers={
            "Authorization": f"Bearer {config.TURSO_API_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read()).get("error", "")
        except Exception:
            msg = ""
        if exc.code in (401, 403):
            msg = "the API token was rejected - check TURSO_API_TOKEN"
        raise TursoAdminError(f"Turso API error {exc.code}: {msg or 'request failed'}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise TursoAdminError(f"Could not reach the Turso API ({exc.__class__.__name__}).") from None


def _org():
    return f"/v1/organizations/{config.TURSO_ORG}"


def database_name(slug: str) -> str:
    return f"{config.TURSO_DB_PREFIX}-{slug}"[:60].strip("-")


def get_database(name: str):
    """Hostname of an existing database, or None."""
    try:
        info = _call("GET", f"{_org()}/databases/{name}")
    except TursoAdminError as exc:
        if " 404" in str(exc):
            return None
        raise
    return (info.get("database") or {}).get("Hostname")


def create_database(name: str):
    """Create a database in the configured group. Returns (hostname, created_now)."""
    existing = get_database(name)
    if existing:
        return existing, False
    info = _call("POST", f"{_org()}/databases",
                 {"name": name, "group": config.TURSO_GROUP})
    host = (info.get("database") or {}).get("Hostname")
    if not host:
        raise TursoAdminError("Turso did not return a hostname for the new database.")
    return host, True


def delete_database(name: str) -> None:
    try:
        _call("DELETE", f"{_org()}/databases/{name}")
    except TursoAdminError:
        pass


def list_databases():
    info = _call("GET", f"{_org()}/databases")
    return [d.get("Name") for d in info.get("databases", [])]


def mint_group_token() -> str:
    """A full-access token valid for every database in the group."""
    info = _call(
        "POST", f"{_org()}/groups/{config.TURSO_GROUP}/auth/tokens",
        query="?expiration=never&authorization=full-access",
    )
    jwt = info.get("jwt")
    if not jwt:
        raise TursoAdminError("Turso did not return a token.")
    return jwt
