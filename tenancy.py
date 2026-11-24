"""Per-request "current university" (tenant).

Every university has its own SQLite database file. The request middleware
(middleware.py) or a login/registration handler sets the current tenant, and
database.get_connection() opens that university's database. Because the
connection itself is tenant-bound, no query can read another university's data.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class TenantNotSelected(RuntimeError):
    """Raised when university data is requested outside a university context."""


@dataclass(frozen=True)
class Tenant:
    id: int
    slug: str
    name: str
    db_path: Path


_current: ContextVar[Optional[Tenant]] = ContextVar("current_tenant", default=None)


def current_tenant() -> Optional[Tenant]:
    return _current.get()


def require_tenant() -> Tenant:
    tenant = _current.get()
    if tenant is None:
        raise TenantNotSelected("No university is selected for this request.")
    return tenant


def set_tenant(tenant: Optional[Tenant]):
    """Low-level: returns a token for reset_tenant()."""
    return _current.set(tenant)


def reset_tenant(token) -> None:
    _current.reset(token)


@contextmanager
def use_tenant(tenant: Tenant):
    token = _current.set(tenant)
    try:
        yield tenant
    finally:
        _current.reset(token)
