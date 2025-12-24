"""Web UI routes for Tessera."""

import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.config import settings
from tessera.db import UserDB, get_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["web"])


class LoginRequiredError(Exception):
    """Exception raised when login is required."""

    pass


# Exception handler for login required - will be registered with the app
def register_login_required_handler(app: Any) -> None:
    """Register exception handler for LoginRequiredError."""
    from starlette.requests import Request as StarletteRequest

    async def login_required_handler(
        request: StarletteRequest, exc: LoginRequiredError
    ) -> RedirectResponse:
        return RedirectResponse(url="/login", status_code=302)

    app.add_exception_handler(LoginRequiredError, login_required_handler)


# Template directory
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_hasher = PasswordHasher()


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any] | None:
    """Get current logged-in user from session."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None

    try:
        result = await session.execute(
            select(UserDB).where(UserDB.id == UUID(user_id)).where(UserDB.deactivated_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if user:
            return {
                "id": str(user.id),
                "email": user.email,
                "name": user.name,
                "role": user.role.value,
                "team_id": str(user.team_id) if user.team_id else None,
            }
    except Exception as e:
        logger.warning("Failed to get current user from session: %s: %s", type(e).__name__, e)
    return None


async def require_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Require a logged-in user, redirect to login if not authenticated."""
    user = await get_current_user(request, session)
    if not user:
        raise LoginRequiredError()
    return user


def make_context(
    request: Request,
    active_page: str,
    current_user: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Create template context with common variables."""
    return {
        "request": request,
        "active_page": active_page,
        "current_user": current_user,
        **kwargs,
    }


@router.get("/login", response_class=HTMLResponse, response_model=None)
async def login_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Login page."""
    current_user = await get_current_user(request, session)
    if current_user:
        return RedirectResponse(url="/", status_code=302)
    error = request.query_params.get("error")
    return templates.TemplateResponse(
        "login.html",
        make_context(request, "login", error=error),
    )


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Handle login form submission."""
    # Look up user by email
    result = await session.execute(
        select(UserDB).where(UserDB.email == email).where(UserDB.deactivated_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if not user or not user.password_hash:
        return RedirectResponse(url="/login?error=invalid", status_code=302)

    # Verify password
    try:
        _hasher.verify(user.password_hash, password)
    except VerifyMismatchError:
        return RedirectResponse(url="/login?error=invalid", status_code=302)

    # Set session
    request.session["user_id"] = str(user.id)
    return RedirectResponse(url="/", status_code=302)


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    """Handle logout."""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: dict[str, Any] = Depends(require_current_user),
) -> HTMLResponse:
    """Dashboard page."""
    return templates.TemplateResponse(
        "dashboard.html",
        make_context(request, "dashboard", current_user),
    )


@router.get("/users", response_class=HTMLResponse)
async def users_list(
    request: Request,
    current_user: dict[str, Any] = Depends(require_current_user),
) -> HTMLResponse:
    """Users list page."""
    return templates.TemplateResponse(
        "users.html",
        make_context(request, "users", current_user),
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail(
    request: Request,
    user_id: str,
    current_user: dict[str, Any] = Depends(require_current_user),
) -> HTMLResponse:
    """User detail page."""
    return templates.TemplateResponse(
        "user_detail.html",
        make_context(request, "users", current_user, user_id=user_id),
    )


@router.get("/teams", response_class=HTMLResponse)
async def teams_list(
    request: Request,
    current_user: dict[str, Any] = Depends(require_current_user),
) -> HTMLResponse:
    """Teams list page."""
    return templates.TemplateResponse(
        "teams.html",
        make_context(request, "teams", current_user),
    )


@router.get("/teams/{team_id}", response_class=HTMLResponse)
async def team_detail(
    request: Request,
    team_id: str,
    current_user: dict[str, Any] = Depends(require_current_user),
) -> HTMLResponse:
    """Team detail page."""
    return templates.TemplateResponse(
        "team_detail.html",
        make_context(request, "teams", current_user, team_id=team_id),
    )


@router.get("/assets", response_class=HTMLResponse)
async def assets_list(
    request: Request,
    current_user: dict[str, Any] = Depends(require_current_user),
) -> HTMLResponse:
    """Assets list page."""
    return templates.TemplateResponse(
        "assets.html",
        make_context(request, "assets", current_user),
    )


@router.get("/assets/{asset_id}", response_class=HTMLResponse)
async def asset_detail(
    request: Request,
    asset_id: str,
    current_user: dict[str, Any] = Depends(require_current_user),
) -> HTMLResponse:
    """Asset detail page."""
    return templates.TemplateResponse(
        "asset_detail.html",
        make_context(request, "assets", current_user, asset_id=asset_id),
    )


@router.get("/contracts", response_class=HTMLResponse)
async def contracts_list(
    request: Request,
    current_user: dict[str, Any] = Depends(require_current_user),
) -> HTMLResponse:
    """Contracts list page."""
    return templates.TemplateResponse(
        "contracts.html",
        make_context(request, "contracts", current_user),
    )


@router.get("/contracts/{contract_id}", response_class=HTMLResponse)
async def contract_detail(
    request: Request,
    contract_id: str,
    current_user: dict[str, Any] = Depends(require_current_user),
) -> HTMLResponse:
    """Contract detail page."""
    return templates.TemplateResponse(
        "contract_detail.html",
        make_context(request, "contracts", current_user, contract_id=contract_id),
    )


@router.get("/proposals", response_class=HTMLResponse)
async def proposals_list(
    request: Request,
    current_user: dict[str, Any] = Depends(require_current_user),
) -> HTMLResponse:
    """Proposals list page."""
    return templates.TemplateResponse(
        "proposals.html",
        make_context(request, "proposals", current_user),
    )


@router.get("/proposals/{proposal_id}", response_class=HTMLResponse)
async def proposal_detail(
    request: Request,
    proposal_id: str,
    current_user: dict[str, Any] = Depends(require_current_user),
) -> HTMLResponse:
    """Proposal detail page."""
    return templates.TemplateResponse(
        "proposal_detail.html",
        make_context(request, "proposals", current_user, proposal_id=proposal_id),
    )


@router.get("/import", response_class=HTMLResponse, response_model=None)
async def import_page(
    request: Request,
    current_user: dict[str, Any] = Depends(require_current_user),
) -> Response:
    """Import manifest page (admin only)."""
    if current_user.get("role") != "admin":
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        "import.html",
        make_context(request, "import", current_user),
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    current_user: dict[str, Any] = Depends(require_current_user),
) -> HTMLResponse:
    """User settings page for notification preferences."""
    return templates.TemplateResponse(
        "settings.html",
        make_context(
            request,
            "settings",
            current_user,
            slack_configured=bool(settings.slack_webhook_url),
        ),
    )


@router.get("/admin/audit", response_class=HTMLResponse, response_model=None)
async def audit_log_page(
    request: Request,
    current_user: dict[str, Any] = Depends(require_current_user),
) -> Response:
    """Admin audit log page."""
    if current_user.get("role") != "admin":
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        "audit_log.html",
        make_context(request, "audit", current_user),
    )
