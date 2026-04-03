from fastapi import APIRouter

from app.auth.router import router as auth_router
from app.meeting.router import router as meeting_router
from app.user.router import router as users_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(meeting_router, prefix="/meetings")
