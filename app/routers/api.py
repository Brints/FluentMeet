from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.meeting.router import router as meeting_router
from app.modules.meeting.ws_router import router as ws_router
from app.modules.user.router import router as users_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(meeting_router, prefix="/meetings")
api_router.include_router(ws_router, prefix="/ws")
