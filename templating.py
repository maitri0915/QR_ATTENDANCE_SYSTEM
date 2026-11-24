"""One shared Jinja2 environment so every page gets the same branding, the
signed-in user (needed by the navigation bar) and the current university's
name."""

from fastapi import Request
from fastapi.templating import Jinja2Templates

import config
from auth import get_current_user
from tenancy import current_tenant


def _context(request: Request) -> dict:
    tenant = current_tenant()
    return {
        "current_user": get_current_user(request),
        # University name inside a university workspace, otherwise the platform label.
        "college_name": tenant.name if tenant else config.PLATFORM_LABEL,
        "in_university": tenant is not None,
    }


templates = Jinja2Templates(
    directory=str(config.BASE_DIR / "templates"),
    context_processors=[_context],
)
templates.env.globals.update(
    app_name=config.APP_NAME,
    support_email=config.SUPPORT_EMAIL,
)
