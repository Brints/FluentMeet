"""FastAPI dependencies for the meeting feature package."""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.meeting.repository import MeetingRepository
from app.meeting.service import MeetingService
from app.meeting.state import MeetingStateService


def get_meeting_repository(db: Session = Depends(get_db)) -> MeetingRepository:
    """Provide a MeetingRepository wired to the current DB session."""
    return MeetingRepository(db=db)


def get_meeting_state_service() -> MeetingStateService:
    """Provide the Redis-backed state service.

    Instantiates its own internally cached redis client if not passed.
    """
    return MeetingStateService()


def get_meeting_service(
    repo: MeetingRepository = Depends(get_meeting_repository),
    state: MeetingStateService = Depends(get_meeting_state_service),
) -> MeetingService:
    """Provide the high-level business logic service."""
    return MeetingService(repo=repo, state=state)
