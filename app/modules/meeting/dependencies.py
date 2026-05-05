"""FastAPI dependencies for the meeting feature package."""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.meeting.repository import MeetingRepository
from app.modules.meeting.service import MeetingService
from app.modules.meeting.state import MeetingStateService


def get_meeting_repository(db: Session = Depends(get_db)) -> MeetingRepository:
    """Provide a MeetingRepository wired to the current DB session.

    Args:
        db (Session): Database transaction manager natively injected.
            Defaults to Depends(get_db).

    Returns:
        MeetingRepository: Concrete repository abstraction initialized natively.
    """
    return MeetingRepository(db=db)


def get_meeting_state_service() -> MeetingStateService:
    """Provide the Redis-backed state service.

    Instantiates its own internally cached redis client if not passed.

    Returns:
        MeetingStateService: Native async Redis driver wrapping operations reliably.
    """
    return MeetingStateService()


def get_meeting_service(
    repo: MeetingRepository = Depends(get_meeting_repository),
    state: MeetingStateService = Depends(get_meeting_state_service),
) -> MeetingService:
    """Provide the high-level business logic service.

    Args:
        repo (MeetingRepository): The DB layer. Defaults to
            Depends(get_meeting_repository).
        state (MeetingStateService): The Redis KV layer natively injected
            seamlessly. Defaults to Depends(get_meeting_state_service).

    Returns:
        MeetingService: Composed struct tracking meeting implementations securely.
    """
    return MeetingService(repo=repo, state=state)
