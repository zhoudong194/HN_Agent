"""
base_framework/base/security.py — JWT encode/decode, password hashing, CurrentUser.

Uses bcrypt directly to avoid passlib 1.7.4 + bcrypt >= 4.1 incompatibility.
JWT_SECRET is read from env; generates ephemeral secret if not set.
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set

import bcrypt
from jose import JWTError, jwt

JWT_ALGORITHM = "HS256"
JWT_TTL_HOURS = int(os.getenv("JWT_TTL_HOURS", "8"))


def _resolve_secret() -> str:
    secret = (os.getenv("JWT_SECRET") or "").strip()
    if not secret:
        secret = secrets.token_urlsafe(48)
        logging.getLogger(__name__).warning(
            "JWT_SECRET not set; generated ephemeral secret. "
            "Set JWT_SECRET in .env for stable sessions across restarts."
        )
    return secret


JWT_SECRET = _resolve_secret()


def hash_password(plain: str) -> str:
    """bcrypt hash, truncated to 72 bytes per bcrypt requirement."""
    pw = plain.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=10)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed or not plain:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    user_id: str,
    tenant_id: str,
    email: str,
    roles: List[str],
    permissions: List[str],
) -> str:
    """Sign a short-lived JWT carrying identity + role claims."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "email": email,
        "roles": list(roles),
        "perms": sorted(set(permissions)),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_TTL_HOURS)).timestamp()),
        "jti": secrets.token_urlsafe(8),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Return the JWT payload or None if invalid / expired."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        logging.getLogger(__name__).debug("JWT decode failed: %s", e)
        return None


@dataclass
class CurrentUser:
    """Authenticated user identity with roles and permissions."""
    user_id: str
    tenant_id: str
    email: str
    display_name: str
    is_active: bool
    roles: List[str] = field(default_factory=list)
    permissions: Set[str] = field(default_factory=set)

    def has_permission(self, perm: str) -> bool:
        return perm in self.permissions

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def is_admin(self) -> bool:
        return "tenant_admin" in self.roles
