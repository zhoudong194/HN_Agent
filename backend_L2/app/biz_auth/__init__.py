"""
biz_auth/__init__.py — Biz auth domain entry point.
Exports api_router for automatic discovery by main.py.
"""

from fastapi import APIRouter

from biz_auth.user.api import router as user_router
from biz_auth.role.api import router as role_router

api_router = APIRouter()
api_router.include_router(user_router)
api_router.include_router(role_router)

__all__ = ["api_router"]
