"""Constants for the meeting feature package."""

import enum
from typing import Final

# ── Magic Numbers & Defaults ──────────────────────────────────────────
ROOM_CODE_BYTE_LENGTH: Final = 9
MAX_ROOM_CODE_RETRIES: Final = 5
DEFAULT_ROOM_SETTINGS: Final = {
    "lock_room": False,
    "enable_transcription": False,
    "max_participants": 20,
}


# ── Enums ─────────────────────────────────────────────────────────────
class RoomStatus(enum.StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    ENDED = "ended"


class ParticipantRole(enum.StrEnum):
    HOST = "host"
    GUEST = "guest"


class InvitationStatus(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"


# ── Response messages ─────────────────────────────────────────────────
MSG_ROOM_CREATED = "Room created successfully."
MSG_ROOM_DETAILS = "Room details retrieved successfully."
MSG_ROOM_JOINED = "Joined room successfully."
MSG_ROOM_LEFT = "Left room successfully."
MSG_USER_ADMITTED = "User admitted to room."
MSG_MEETING_ENDED = "Meeting ended successfully."
MSG_ROOM_CONFIG_UPDATED = "Room configuration updated."
MSG_MEETING_HISTORY = "Meeting history retrieved successfully."
MSG_INVITATIONS_SENT = "Meeting invitations sent."


# ── Redis Key Patterns ────────────────────────────────────────────────
def key_room_participants(room_code: str) -> str:
    return f"room:{room_code}:participants"


def key_room_lobby(room_code: str) -> str:
    return f"room:{room_code}:lobby"


def key_room_active_speaker(room_code: str) -> str:
    return f"room:{room_code}:active_speaker"
