"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.core.roles import ExperienceRole, parse_experience_role


async def get_experience_role(
    x_experience_role: Annotated[str | None, Header(alias="X-Experience-Role")] = None,
) -> ExperienceRole:
    """Read the login-free experience role from a request header."""

    try:
        return parse_experience_role(x_experience_role)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_experience_role",
                "message": str(exc),
            },
        ) from exc


def require_roles(
    *allowed_roles: ExperienceRole,
) -> Callable[[ExperienceRole], ExperienceRole]:
    """Create a dependency that permits only the selected experience roles."""

    if not allowed_roles:
        raise ValueError("require_roles needs at least one allowed role")

    allowed = frozenset(allowed_roles)

    async def dependency(
        role: ExperienceRole = Depends(get_experience_role),
    ) -> ExperienceRole:
        if role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "insufficient_experience_role",
                    "message": "The selected experience role cannot perform this operation.",
                    "current_role": role.value,
                    "required_roles": sorted(item.value for item in allowed),
                },
            )
        return role

    return dependency


ExperienceRoleDep = Annotated[ExperienceRole, Depends(get_experience_role)]
