### Feature: Implement Meeting Room Creation & Participant Management

**Problem**
FluentMeet has no mechanism for creating or managing meeting rooms. There are no database models for rooms or participants, no API endpoints for creating meetings or joining them, and no live room state management. Without this foundation, none of the real-time features (audio streaming, captions, translation) have a room context to operate within. Additionally, the participant experience requires a pre-join lobby for hardware testing and a waiting room for host-controlled admission, neither of which exists.

**Proposed Solution**
Implement the full meeting room lifecycle: creation, joining, participant state tracking, active speaker detection, and meeting history. Persistent room metadata will be stored in PostgreSQL (via SQLAlchemy), while ephemeral live room state (participant presence, audio levels, hardware flags) will be stored in Redis for fast read/write access during an active meeting. Cryptographically secure, URL-safe room IDs will be generated to prevent room enumeration attacks.

**User Stories**
*   **As a host,** I want to create a meeting room and receive a shareable link, so I can invite participants without exposing internal IDs.
*   **As a participant,** I want to join a meeting via a room link and pass through a lobby to test my microphone and camera before entering, so I feel prepared before the meeting starts.
*   **As a host,** I want to see which participants are in the lobby waiting to join, and admit or reject them individually, so I control who enters my meeting.
*   **As a participant,** I want the active speaker to be visually highlighted in the UI, so I always know who is currently talking.
*   **As a host,** I want to view a history of my past meetings, so I can reference them for follow-up.

**Acceptance Criteria**
1.  **Database Models** are implemented and migrated:
    *   `Room`: `id`, `room_code` (URL-safe, cryptographically random, 12 chars), `host_id` (FK → `users`), `name`, `status` (`pending | active | ended`), `created_at`, `ended_at`, `settings` (JSON: `lock_room`, `enable_transcription`, `max_participants`).
    *   `Participant`: `id`, `room_id` (FK → `rooms`), `user_id` (FK → `users`), `joined_at`, `left_at`, `role` (`host | guest`).
2.  **Redis Room State** schema is defined and documented:
    ```
    room:{room_code}:participants  → Hash { user_id: JSON(status, language, hardware_ready) }
    room:{room_code}:lobby         → Set { user_id, ... }
    room:{room_code}:active_speaker → String(user_id)
    ```
3.  **REST Endpoints** are implemented under `/api/v1/meetings`:

    | Method  | Endpoint                       | Description                                                     |
    |---------|--------------------------------|-----------------------------------------------------------------|
    | `POST`  | `/`                            | Create a new room. Returns `{ room_code, join_url }`.           |
    | `GET`   | `/{room_code}`                 | Get room details and current participant count.                 |
    | `POST`  | `/{room_code}/join`            | Join a room (places user in lobby if `lock_room=true`).         |
    | `POST`  | `/{room_code}/admit/{user_id}` | Host admits a user from the lobby.                              |
    | `POST`  | `/{room_code}/leave`           | Remove self from room; triggers Redis cleanup.                  |
    | `POST`  | `/{room_code}/end`             | Host ends the meeting; sets `status=ended`, records `ended_at`. |
    | `PATCH` | `/{room_code}/config`          | Update room settings (`lock_room`, `enable_transcription`).     |
    | `GET`   | `/history`                     | Paginated list of past meetings hosted by the current user.     |

4.  **Active Speaker Detection** logic runs server-side:
    *   Audio level metadata is sent from the client via the signaling WebSocket.
    *   The backend updates `room:{room_code}:active_speaker` in Redis when a participant's audio level exceeds a configurable threshold for ≥ 300ms.
    *   A WebSocket broadcast notifies all room participants of the active speaker change.
5.  **Lobby / Waiting Room**:
    *   When `lock_room=true`, joining participants are added to `room:{room_code}:lobby` and notified they are waiting.
    *   The host receives a WebSocket event when a user enters the lobby.
    *   On admission, the user is moved from the lobby to `room:{room_code}:participants`.
6.  All room endpoints require authentication. Only the room host can call `/end`, `/admit`, and `/config`.
7.  Joining a room with `status=ended` returns `404 Not Found`.
8.  Unit and integration tests cover the full room lifecycle.

**Proposed Technical Details**
*   **Room Code Generation**: `secrets.token_urlsafe(9)` produces a 12-character URL-safe string. Collision is checked against the database before persisting.
*   **SQLAlchemy Models**: New `Room` and `Participant` models in `app/models/room.py`.
*   **Pydantic Schemas**: `RoomCreate`, `RoomResponse`, `ParticipantResponse` in `app/schemas/room.py`.
*   **CRUD Layer**: `app/crud/room.py` for all database read/write operations.
*   **Redis Client**: The existing Redis connection (from `app/core/config.py`) is used via an async dependency `get_redis`.
*   **Active Speaker Threshold**: Configurable via `ACTIVE_SPEAKER_THRESHOLD_DB` in settings (default: `-40 dBFS`).
*   **New/Modified Files**:
    *   `app/models/room.py` [NEW]
    *   `app/schemas/room.py` [NEW]
    *   `app/crud/room.py` [NEW]
    *   `app/api/v1/endpoints/meetings.py` [NEW]
    *   `app/services/room_state.py` — Redis-backed live room state helpers [NEW]
    *   `app/api/v1/api.py` — register meetings router [MODIFY]

**Tasks**
- [ ] Implement `Room` and `Participant` SQLAlchemy models in `app/models/room.py`.
- [ ] Generate and apply an Alembic migration for the new tables.
- [ ] Implement Pydantic schemas in `app/schemas/room.py`.
- [ ] Implement CRUD operations in `app/crud/room.py`.
- [ ] Implement Redis room state helpers in `app/services/room_state.py` (join, leave, lobby, active speaker).
- [ ] Implement all REST endpoints in `app/api/v1/endpoints/meetings.py`.
- [ ] Implement lobby admit/reject flow with host WebSocket notification.
- [ ] Implement server-side active speaker detection and broadcast.
- [ ] Register the meetings router in `app/api/v1/api.py`.
- [ ] Write unit tests for CRUD operations and room state helpers.
- [ ] Write integration tests for the full room lifecycle (create → join → end).

**Open Questions/Considerations**
*   Should the waiting room be enabled by default for all rooms, or opt-in per room via the `lock_room` setting?
*   What is the maximum number of participants per room, and should this be enforced at the API level, the Redis level, or both?
*   Should ended meeting rooms be soft-deleted (retained for history) or hard-deleted after a retention period (e.g., 90 days)?
*   For the `/history` endpoint, should it also return meetings the user *participated in* as a guest, or only meetings they hosted?