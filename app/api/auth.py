from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException, status

from app.config import settings


@dataclass(slots=True)
class AuthContext:
    """Per-request auth resolution.

    - ``project_id`` is populated when ``PROJECT_KEYS`` is configured and the
      X-API-Key header maps to a project; callers must treat it as authoritative
      and reject any request-body ``projectId`` that disagrees with it.
    - ``project_id`` is ``None`` when only the legacy single ``TEST_AGENT_API_KEY``
      is configured; in that case the body must carry ``projectId``.
    """

    project_id: str | None


async def require_api_key(x_api_key: str | None = Header(default=None)) -> AuthContext:
    if settings.project_keys:
        if not x_api_key or x_api_key not in settings.project_keys:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key.",
            )
        return AuthContext(project_id=settings.project_keys[x_api_key])

    if settings.api_key:
        if x_api_key != settings.api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key.",
            )
    return AuthContext(project_id=None)
