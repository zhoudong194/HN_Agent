"""
auth.py — password hashing, JWT encode/decode, and CurrentUser model.

Uses bcrypt directly (not passlib) to avoid the well-known incompatibility
between passlib 1.7.4 and bcrypt >= 4.1 ("AttributeError: module 'bcrypt'
has no attribute '__about__'"). bcrypt 5.x still exposes the simple
hashpw / checkpw / gensalt API we need.

Configuration
-------------
JWT_SECRET, JWT_ALGORITHM, JWT_TTL_HOURS read from config (loaded from .env).
A startup-time SECRET is generated if JWT_SECRET is empty, so dev defaults
are safe but each restart rotates the secret (sessions invalidate). Set
JWT_SECRET in .env for stable sessions.
"""

from __future__ import annotations

import logging
import os
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set

import bcrypt
from jose import JWTError, jwt

import config

log = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
JWT_TTL_HOURS = int(os.getenv("JWT_TTL_HOURS", "8"))


def _resolve_secret() -> str:
    secret = (os.getenv("JWT_SECRET") or "").strip()
    if not secret:
        # Ephemeral secret — sessions will invalidate on each restart.
        secret = secrets.token_urlsafe(48)
        log.warning(
            "JWT_SECRET not set; generated an ephemeral one. "
            "Set JWT_SECRET in .env for stable sessions across restarts."
        )
    return secret


JWT_SECRET = _resolve_secret()


# ----------------------------------------------------------------------
# Password hashing
# ----------------------------------------------------------------------
def hash_password(plain: str) -> str:
    """bcrypt hash with the 72-byte truncation bcrypt requires."""
    pw = plain.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=10)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed or not plain:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


# ----------------------------------------------------------------------
# JWT encode/decode
# ----------------------------------------------------------------------
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
        log.debug("JWT decode failed: %s", e)
        return None


# ----------------------------------------------------------------------
# CurrentUser — passed to handlers that need identity + permissions
# ----------------------------------------------------------------------
@dataclass
class CurrentUser:
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


def load_user(user_id: str) -> Optional[CurrentUser]:
    """
    Look up a user by id and assemble their roles + effective permissions.
    Returns None if the user is missing or inactive.
    """
    from database import _PooledConn  # local import to avoid cycles

    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, tenant_id, email, display_name, is_active
            FROM rbac.users WHERE id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        uid, tid, email, name, is_active = row
        if not is_active:
            return None

        cur.execute(
            """
            SELECT r.name
            FROM rbac.roles r
            JOIN rbac.user_roles ur ON ur.role_id = r.id
            WHERE ur.user_id = %s
            """,
            (user_id,),
        )
        roles = [r[0] for r in cur.fetchall()]

        cur.execute(
            """
            SELECT DISTINCT rp.permission_key
            FROM rbac.role_permissions rp
            JOIN rbac.user_roles ur ON ur.role_id = rp.role_id
            WHERE ur.user_id = %s
            """,
            (user_id,),
        )
        perms = {r[0] for r in cur.fetchall()}

    return CurrentUser(
        user_id=str(uid),
        tenant_id=str(tid),
        email=email,
        display_name=name,
        is_active=bool(is_active),
        roles=roles,
        permissions=perms,
    )