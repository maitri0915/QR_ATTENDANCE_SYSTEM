"""Binds each request to the university stored in the signed session cookie."""

from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse

import platform_db
from tenancy import reset_tenant, set_tenant


class TenantMiddleware:
    """Pure ASGI middleware (must sit *inside* SessionMiddleware).

    For a signed-in university user it loads the university from the platform
    database on every request. If the university was suspended or removed, the
    user is signed out immediately - suspension takes effect at once, not at
    the next login."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].startswith("/static"):
            await self.app(scope, receive, send)
            return

        session = scope.get("session")
        user = session.get("user") if isinstance(session, dict) else None
        slug = user.get("university") if isinstance(user, dict) else None

        if not slug:
            await self.app(scope, receive, send)
            return

        tenant = await run_in_threadpool(platform_db.get_active_tenant, slug)

        if tenant is None:
            session.clear()
            await RedirectResponse("/?notice=university-unavailable", 303)(
                scope, receive, send
            )
            return

        token = set_tenant(tenant)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_tenant(token)
