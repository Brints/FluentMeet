### Feature: Implement GET /history & PATCH /{room_code}/config — Meeting Management Supplementary Endpoints

**Problem**
The core room lifecycle endpoints (create, join, leave, end) are covered in the [Room & Meeting Management issue](./room_meeting.md). However, two supporting capabilities are still missing: hosts cannot review past meetings, and room settings cannot be changed after a room has been created. Without meeting history, hosts have no record of their activity. Without a config endpoint, settings like `lock_room` and `enable_transcription` are fixed at creation time and cannot adapt to the meeting's needs as it progresses.

**Proposed Solution**
Implement two endpoints as part of the existing `app/api/v1/endpoints/meetings.py` router:
- `GET /api/v1/meetings/history` — paginated list of meetings hosted by the authenticated user, ordered by recency.
- `PATCH /api/v1/meetings/{room_code}/config` — partial update of a room's live settings, callable only by the host and only while the meeting is `active`.

**User Stories**
*   **As a host,** I want to view a list of my past meetings with their date, duration, and participant count, so I can reference previous sessions and follow up with participants.
*   **As a host,** I want to lock my room mid-meeting to prevent new participants from joining, so I can control access once the session has started.
*   **As a host,** I want to toggle live transcription on or off during a meeting, so I can enable it only when participants need it.

**Acceptance Criteria**

#### GET /api/v1/meetings/history
1.  Requires a valid `Authorization: Bearer <access_token>` header.
2.  Returns a paginated list of meetings where `host_id = current_user.id` and `status = "ended"`:
    ```json
    {
      "total": 42,
      "page": 1,
      "page_size": 20,
      "items": [
        {
          "room_code": "abc123xyz",
          "name": "Weekly Sync",
          "created_at": "2026-03-14T10:00:00Z",
          "ended_at": "2026-03-14T11:02:00Z",
          "duration_minutes": 62,
          "participant_count": 5
        }
      ]
    }
    ```
3.  Supports `?page=1&page_size=20` query parameters. `page_size` is capped at 100.
4.  `duration_minutes` is computed as `(ended_at - created_at).total_seconds() / 60`, rounded to the nearest minute.
5.  `participant_count` is the count of distinct `Participant` records for the room.

#### PATCH /api/v1/meetings/{room_code}/config
1.  Requires a valid `Authorization: Bearer <access_token>` header.
2.  Returns `403 Forbidden` if the authenticated user is not the room's host.
3.  Returns `404 Not Found` if the `room_code` does not exist.
4.  Returns `400 Bad Request` with code `ROOM_NOT_ACTIVE` if the room's `status` is not `"active"`.
5.  Accepts a JSON body with any combination of the following fields (all optional):
    ```json
    {
      "lock_room": true,
      "enable_transcription": false,
      "max_participants": 10
    }
    ```
6.  Updates the `room.settings` JSON column in PostgreSQL with the provided fields (partial merge — unspecified keys retain their current values).
7.  Broadcasts a WebSocket event to all room participants to propagate the config change in real-time:
    ```json
    { "event": "room_config_updated", "settings": { "lock_room": true, "enable_transcription": false } }
    ```
8.  Returns `200 OK` with the full updated room settings.

**Proposed Technical Details**
*   **Router**: `app/api/v1/endpoints/meetings.py` — adds `GET /history` and `PATCH /{room_code}/config` to the existing meetings router.
*   **Schemas** in `app/schemas/room.py`:
    *   `MeetingHistoryItem` — `room_code`, `name`, `created_at`, `ended_at`, `duration_minutes`, `participant_count`.
    *   `PaginatedMeetingHistory` — `total`, `page`, `page_size`, `items: list[MeetingHistoryItem]`.
    *   `RoomConfigUpdate` — `lock_room: bool | None`, `enable_transcription: bool | None`, `max_participants: int | None`.
*   **CRUD** in `app/crud/room.py`:
    *   `get_meeting_history(db, host_id, page, page_size) -> tuple[int, list[Room]]`
    *   `update_room_config(db, room, config: RoomConfigUpdate) -> Room`
*   **WebSocket Broadcast**: `ConnectionManager.broadcast_to_room(room_code, message)` called after config update (reuses the `ConnectionManager` from the [Real-Time Audio issue](./realtime_audio.md)).
*   **New/Modified Files**:
    *   `app/api/v1/endpoints/meetings.py` — add the two routes [MODIFY]
    *   `app/schemas/room.py` — add `MeetingHistoryItem`, `PaginatedMeetingHistory`, `RoomConfigUpdate` [MODIFY]
    *   `app/crud/room.py` — add `get_meeting_history`, `update_room_config` [MODIFY]

**Tasks**
- [ ] Add `MeetingHistoryItem`, `PaginatedMeetingHistory`, and `RoomConfigUpdate` to `app/schemas/room.py`.
- [ ] Implement `get_meeting_history` in `app/crud/room.py` (with `participant_count` subquery).
- [ ] Implement `GET /api/v1/meetings/history` with pagination support.
- [ ] Implement `update_room_config` in `app/crud/room.py` (partial JSON merge).
- [ ] Implement `PATCH /api/v1/meetings/{room_code}/config` with host-only guard and active-room check.
- [ ] Integrate `ConnectionManager.broadcast_to_room` to push the config change to connected participants.
- [ ] Write unit tests for `get_meeting_history` and `update_room_config` CRUD.
- [ ] Write integration tests: history pagination, config update (host, non-host `403`, ended room `400`), and WebSocket broadcast.

**Open Questions/Considerations**
*   Should `GET /history` also include meetings the user participated in as a **guest**, not just meetings they hosted? If so, it needs a separate query and a `role` filter parameter.
*   Should `PATCH /{room_code}/config` also be callable for `pending` rooms (before the meeting starts), or strictly limited to `active` rooms?
*   If `lock_room` is set to `true` mid-meeting, should participants already in the lobby be automatically rejected, or should the host still manually admit or reject them?
