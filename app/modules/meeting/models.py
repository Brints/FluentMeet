"""Meeting Database Models module."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.modules.meeting.constants import DEFAULT_ROOM_SETTINGS


def utc_now() -> datetime:
    return datetime.now(UTC)


class Room(Base):
    """Database model storing standard video-conference domains tracking lifecycle securely.

    Attributes:
        id: Native UUID identity struct.
        room_code: Statically allocated human readable string (e.g., `xyz-qwer-vtx`).
        host_id: Foreign key struct tracking origin creator UUID reliably.
        name: Name string locally bound.
        status: Enum string mapped to RoomStatus variants.
        scheduled_at: Optional payload struct defining constraints securely.
        created_at: Tracking identifier logic.
        ended_at: Time validation block mapped transparently natively.
        settings: JSON array payload defining bounds dynamically (e.g., `lock_room`, `max_participants`).
    """

    __tablename__ = "rooms"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, index=True, default=uuid.uuid4
    )
    room_code: Mapped[str] = mapped_column(
        String(12), unique=True, index=True, nullable=False
    )
    host_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), default="pending", index=True, nullable=False
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=DEFAULT_ROOM_SETTINGS, nullable=False
    )


class Participant(Base):
    """Database model mapping User connections locally inside discrete Rooms.

    Attributes:
        id: Primary identity tracker statically tracking interactions locally.
        room_id: FK array tracking parent Room identity natively.
        user_id: Authenticated mapping securely targeting explicit Identity arrays.
        guest_session_id: Unauthenticated visitor string securely generating unique identity maps dynamically.
        display_name: The public identifying string.
        joined_at: Date timestamp explicitly capturing states natively.
        left_at: Bounds logic natively tracked array identifiers seamlessly dynamically.
        role: Internal target natively isolating Guest vs Host restrictions natively explicitly bounding definitions natively.
    """

    __tablename__ = "participants"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, index=True, default=uuid.uuid4
    )
    room_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rooms.id"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(
        index=True, nullable=True
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    role: Mapped[str] = mapped_column(String(10), default="guest", nullable=False)

    __table_args__ = (
        UniqueConstraint("room_id", "user_id", name="uq_participant_room_user"),
        UniqueConstraint(
            "room_id", "guest_session_id", name="uq_participant_room_guest"
        ),
    )


class MeetingInvitation(Base):
    __tablename__ = "meeting_invitations"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, index=True, default=uuid.uuid4
    )
    room_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rooms.id"), index=True, nullable=False
    )
    inviter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="pending", nullable=False)
    token: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
