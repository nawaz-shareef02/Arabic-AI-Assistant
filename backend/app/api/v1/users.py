"""
Users API Router — Reserved Future Endpoint.

This module is a placeholder for user profile management, preferences,
and enterprise user administration scheduled for future sprints.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/users", tags=["USERS"])


@router.get("/", summary="Users endpoint status (Future Reserved)")
async def read_users():
    return {
        "status": "reserved",
        "message": "Users management API is reserved for future enterprise administration releases.",
    }