"""Authentication routes for Tessera."""

import logging
from typing import Any
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.config import settings
from tessera.db import UserDB, get_session
from tessera.models.enums import UserType

logger = logging.getLogger(__name__)


class LoginRequiredError(Exception):
    """Exception raised when login is required."""

    pass


def register_login_required_handler(app: Any) -> None:
    """Register exception handler for LoginRequiredError."""
    from starlette.requests import Request as StarletteRequest

    async def login_required_handler(
        request: StarletteRequest, exc: LoginRequiredError
    ) -> RedirectResponse:
        return RedirectResponse(url="/login", status_code=302)

    app.add_exception_handler(LoginRequiredError, login_required_handler)


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
                "username": user.username,
                "email": user.email,
                "name": user.name,
                "role": user.role.value,
                "user_type": user.user_type.value,
                "team_id": str(user.team_id) if user.team_id else None,
            }
    except Exception as e:
        logger.warning(
            "Failed to get current user from session: %s: %s",
            type(e).__name__,
            e,
        )
    return None


async def require_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Require a logged-in user, redirect to login if not authenticated.

    When AUTH_DISABLED is true, returns a fake admin user for development.
    """
    if settings.auth_disabled:
        return {
            "id": "00000000-0000-0000-0000-000000000000",
            "username": "dev",
            "email": None,
            "name": "Dev User",
            "role": "admin",
            "user_type": "human",
            "team_id": None,
        }

    user = await get_current_user(request, session)
    if not user:
        raise LoginRequiredError()
    return user


async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Handle login form submission."""
    normalized = username.strip().lower()

    result = await session.execute(
        select(UserDB).where(UserDB.username == normalized).where(UserDB.deactivated_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if not user or not user.password_hash:
        return RedirectResponse(url="/login?error=invalid", status_code=302)

    if user.user_type == UserType.BOT:
        return RedirectResponse(url="/login?error=invalid", status_code=302)

    try:
        _hasher.verify(user.password_hash, password)
    except VerifyMismatchError:
        return RedirectResponse(url="/login?error=invalid", status_code=302)

    request.session["user_id"] = str(user.id)
    return RedirectResponse(url="/", status_code=302)


async def logout(request: Request) -> RedirectResponse:
    """Handle logout."""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)
