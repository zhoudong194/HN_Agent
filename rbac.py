"""
rbac.py — FastAPI dependencies for authentication and authorization.

Provides:
  * require_user              — any authenticated user; 401 if missing/invalid token
  * require_permission(perm)  — like require_user, plus checks a permission string; 403 if missing
  * require_role(role)        — same shape, checks a role string

Tokens come from `Authorization: Bearer <jwt>`. The decoded claims
(user_id, tenant_id, roles, perms) are trusted from the JWT itself,
and `require_user` re-fetches the live user record on a 60-second
in-process TTL cache to keep role changes from leaking.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from fastapi import Depends, Header, HTTPException, status
from cachetools import TTLCache

from auth import CurrentUser, decode_token, load_user

log = logging.getLogger(__name__)

# Cache user_id -> CurrentUser for 60s. Bounded at 1024 to keep memory sane.
_user_cache: "TTLCache[str, CurrentUser]" = TTLCache(maxsize=1024, ttl=60)


def _extract_bearer(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return parts[1].strip()


async def require_user(
    authorization: Optional[str] = Header(default=None),
) -> CurrentUser:
    """Resolve the caller to a CurrentUser. 401 if not authenticated."""
    token = _extract_bearer(authorization)
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token missing sub")

    cached = _user_cache.get(user_id)
    if cached is not None:
        return cached

    user = load_user(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found or inactive")
    _user_cache[user_id] = user
    return user


def require_permission(perm: str) -> Callable:
    """
    Dependency factory: passes through require_user, then 403 if the
    user lacks the given permission key (e.g. "policy:read").
    """
    async def _dep(user: CurrentUser = Depends(require_user)) -> CurrentUser:
        if not user.has_permission(perm):
            log.info("RBAC denied: user=%s need=%s have=%s", user.email, perm, sorted(user.permissions))
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing permission: {perm}",
            )
        return user
    return _dep


def require_role(role: str) -> Callable:
    """Dependency factory: 403 if user is not in the named role."""
    async def _dep(user: CurrentUser = Depends(require_user)) -> CurrentUser:
        if not user.has_role(role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing role: {role}",
            )
        return user
    return _dep


def invalidate_user_cache(user_id: Optional[str] = None) -> None:
    """
    Drop a single user's cache entry (call after role / permission changes),
    or the whole cache if user_id is None.
    """
    if user_id is None:
        _user_cache.clear()
    else:
        _user_cache.pop(user_id, None)