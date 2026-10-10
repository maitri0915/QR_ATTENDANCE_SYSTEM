"""One shared Jinja2 environment so every page gets the same branding
and the signed-in user (needed by the navigation bar)."""

from fastapi import Request
from fastapi.templating import Jinja2Templates

import config
from auth import get_current_user


def _context(request: Request) -> dict:
    return {"current_user": get_current_user(request)}


templates = Jinja2Templates(
    directory=str(config.BASE_DIR / "templates"),
    context_processors=[_context],
)
templates.env.globals.update(
    app_name=config.APP_NAME,
    college_name=config.COLLEGE_NAME,
    support_email=config.SUPPORT_EMAIL,
)
