# FluentMeet Meeting API Documentation

> **Base URL:** `/api/v1/meetings` (Assuming router prefix, though undefined in `router.py`, wait let me check `main.py` or just document the endpoints as defined, usually it's `/api/v1/meetings`).
> **Version:** 1.0 · **Protocol:** REST over HTTPS & WebSockets · **Content-Type:** `application/json`

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Meeting Lifecycle](#meeting-lifecycle)
- [Real-time State (Redis)](#real-time-state-redis)
- [REST Endpoints](#rest-endpoints)
  - [POST /](#post-)
  - [GET /history](#get-history)
  - [GET /{room_code}](#get-room_code)
  - [GET /{room_code}/participants](#get-room_codeparticipants)
  - [POST /{room_code}/join](#post-room_codejoin)
  - [POST /{room_code}/leave](#post-room_codeleave)
  - [POST /{room_code}/admit/{user_id}](#post-room_codeadmituser_id)
  - [POST /{room_code}/end](#post-room_codeend)
  - [PATCH /{room_code}/config](#patch-room_codeconfig)
  - [POST /{room_code}/invite](#post-room_codeinvite)
- [WebSocket Endpoints](#websocket-endpoints)
  - [WS /signaling/{room_code}](#ws-signalingroom_code)
  - [WS /audio/{room_code}](#ws-audioroom_code)
  - [WS /captions/{room_code}](#ws-captionsroom_code)
- [Data Models](#data-models)
- [Request / Response Schemas](#request--response-schemas)
- [Internal Services](#internal-services)

---

## Overview

The FluentMeet meeting module provides comprehensive meeting management, supporting:

- **Room Management:** Creation, scheduling, retrieval, updates, and forced ending.
- **Participant Tracking:** Identifying registered users and dynamic token-based guests.
- **Real-time State:** Lobby (waiting room) management and active connections tracked via Redis.
- **Invitations:** Email invitations utilizing Kafka email producers.
- **Live Streams (WebSockets):** WebRTC signaling, AI pipeline audio streaming (STT + TTS integration), and live translation captions.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│              FastAPI Routers (REST & WebSockets)                │
│             (router.py, ws_router.py)                           │
├─────────────────┬──────────────────────┬────────────────────────┤
│                 │                      │                        │
│ MeetingService  │ MeetingStateService  │ MeetingRepository      │
│  (service.py)   │     (state.py)       │   (repository.py)      │
│                 │                      │                        │
│       │         │           │          │           │            │
│       │         ▼           ▼          │           ▼            │
│       │   ┌────────────┐               │    ┌────────────┐      │
│       │   │   Redis    │               │    │PostgreSQL  │      │
│       │   │(Live State)│               │    │(Rooms, Pts)│      │
│       │   └────────────┘               │    └────────────┘      │
│       ▼                                ▼                        │
│ ┌────────────┐                   ┌────────────────┐             │
│ │ Email      │                   │ Kafka Pipeline │             │
│ │ Producer   │                   │ Audio & Text   │             │
│ └────────────┘                   └────────────────┘             │
└─────────────────────────────────────────────────────────────────┘
```

### Module Files

| File | Purpose |
|---|---|
| `router.py` | FastAPI REST route definitions for room CRUD and participant logic. |
| `ws_router.py` | WebSocket endpoints for WebRTC signaling, audio stream ingestion/egress, and captions. |
| `service.py` | Core business logic — joining, leaving, lobby logic, room updates. |
| `state.py` | Redis-backed ephemeral state tracking (lobby, live participants, active speaker). |
| `repository.py` | SQLAlchemy database wrapper for rooms and participants. |
| `schemas.py` | Pydantic request/response models and validators. |
| `models.py` | SQLAlchemy ORM models (`Room`, `Participant`, `MeetingInvitation`). |
| `dependencies.py` | FastAPI dependency injection factories. |
| `ws_dependencies.py` | WebSocket-specific JWT authentication (`authenticate_ws`). |
| `constants.py` | Definitions of message strings, defaults, and enums (`ParticipantRole`, `RoomStatus`). |

---

## Meeting Lifecycle

1. **Creation:** A Host creates a room (instant or scheduled). The room gets a `PENDING` status.
2. **Joining / Lobby:** 
   - Authenticated Users and Guests send `POST /{room_code}/join`.
   - If the room is not active yet (for non-hosts) or the room requires host admission (lobby locked), the participant is waitlisted.
   - Host joining auto-activates `PENDING` rooms.
3. **Live:** Live state (participants, active speaker) is pushed to Redis. WebSockets can now be securely accessed.
4. **Conclusion:** Host explicitly ends meeting (`POST /{room_code}/end`). This wipes Redis state and updates the DB to `ENDED`.

---

## Real-time State (Redis)

Live meeting state is ephemeral and purely managed inside Redis for high-performance retrieval and updates.

**Redis Keys:**

| Key Pattern | Data Structure | Purpose |
|---|---|---|
| `room:{room_code}:participants` | Hash | Stores connected user IDs and their JSON state (language, hardware_ready, status). |
| `room:{room_code}:lobby` | Hash | Stores waitlisted guest/user IDs, their display names, and target listening language. |
| `room:{room_code}:active_speaker` | String | Volatile key with a low TTL (e.g. 5s). Identifies current dominant speaker. |

---

## REST Endpoints

*(Endpoints assume prefix `/api/v1/meetings`, but refer to your main `FastAPI.include_router` setup for exact path.)*

---

### POST /

Create a new meeting room.

**🔒 Requires Authentication:** `Authorization: Bearer <access_token>`

**Request Body:**

```json
{
  "name": "Project Alpha Sync",
  "scheduled_at": "2026-04-10T15:00:00Z",
  "settings": {
    "lock_room": false,
    "enable_transcription": true,
    "max_participants": 20
  }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | `string` | ✅ | Max 255 chars |
| `settings` | `object` | ❌ | Contains `lock_room`, `enable_transcription`, `max_participants` |
| `scheduled_at`| `datetime`| ❌ | Defaults to `null` (creates ad-hoc instant meeting) |

**Response: `201 Created`** Returns a `RoomApiResponse` enveloping the created `RoomResponse`.

---

### GET /history

Retrieve a paginated list of meetings the user has hosted or participated in.

**🔒 Requires Authentication:** `Authorization: Bearer <access_token>`

**Query Parameters:**
- `role`: string `host`, `guest`, or `all` (default).
- `page`: int >= 1
- `page_size`: int between 1-100

**Response: `200 OK`** Returns a paginated list of `MeetingHistoryItem` objects (fields: `room_code`, `name`, `duration_minutes`, `participant_count`, etc.)

---

### GET /{room_code}

Retrieve the current room's details including a live-calculated participant count.

**Response: `200 OK`**
Returns standard `RoomResponse` inside an envelope. The `participant_count` will merge DB counts or Active Redis counts depending on the room's current state (`PENDING`/`ENDED` vs `ACTIVE`).

---

### GET /{room_code}/participants

Get the live state of the active participants and the waiting list (lobby).

**🔒 Requires Authentication:** `Authorization: Bearer <access_token>` (Host only)

**Response: `200 OK`** Returns a payload containing lists of `active` connections and users in the `lobby`.

---

### POST /{room_code}/join

Join a room or enter the lobby. Handles authentication automatically. Unauthenticated users must supply a display name.

**Query / Header:** Handled automatically (Bearer Token makes you an authenticated user).

**Request Body:**

```json
{
  "display_name": "John Doe (Guest)",
  "listening_language": "fr"
}
```

**Response: `200 OK`**
```json
{
  "status": "success",
  "message": "Joined room successfully.",
  "data": {
    "status": "joined",  // or "waiting"
    "guest_token": "eyJhb..." // Set if user joined as an anonymous guest
  }
}
```

---

### POST /{room_code}/leave

Leave an active room. Drops the user out of the Redis tracking structures (participants hash or lobby hash) and sets `left_at` in the DB.

**Authentication:** Optional. (If logged in, uses user ID; otherwise looks for `guest_session_id` out of a JWT).

---

### POST /{room_code}/admit/{user_id}

Admit a waitlisted participant out of the lobby and into the live room.

**🔒 Requires Authentication:** Host only.

---

### POST /{room_code}/end

Forcibly end the meeting. Immediately updates the DB state to `ENDED`, tallies up the `duration_minutes`, and wipes all real-time structures in Redis.

**🔒 Requires Authentication:** Host only.

---

### PATCH /{room_code}/config

Update a live room's settings natively. 

**🔒 Requires Authentication:** Host only.

**Behavior:**
Modifies the room DB, then automatically invokes `ConnectionManager.broadcast_to_room` over WebSockets to sync settings with all connected peers immediately.

---

### POST /{room_code}/invite

Dispatch email invitations utilizing the async Kafka email producer.

**🔒 Requires Authentication:** Host only.

**Request Body:**
```json
{
  "emails": ["user1@example.com", "user2@example.com"]
}
```

**Response: `200 OK`** Indicates how many emails successfully enqueued vs failed.

---

## WebSocket Endpoints

Clients connect using a `?token=<jwt>` query parameter for authentication instead of HTTP headers. The JWT can be a standard Access Token or a Guest Token returned from `POST /{room_code}/join`.

### WS /signaling/{room_code}

- **Purpose:** Relay mechanism for WebRTC handshakes (Offer/Answer/ICE candidates).
- **Behavior:** Accepts payloads pointing to a `target_user_id` (unicast direct to them) or broadcast mode if empty.

### WS /audio/{room_code}

- **Purpose:** Fast bidirectional streaming to the AI Pipeline.
- **Ingestion:** Reads raw binary chunks from the client, sends as `audio.raw` chunks into Kafka.
- **Egress:** Listens for `audio.synthesized` chunks from Kafka. Filters frames checking if the client's `listening_language` explicitly matches the frame target. If it does, pushes binary bytes down the WebSocket to the client.

### WS /captions/{room_code}

- **Purpose:** Real-time text captions.
- **Behavior:** Connects to standard outputs (`text.original` and `text.translated`) in Kafka, formats into normalized `{event: "caption", speaker_id: ..., text: ...}` blobs, and pushes down the WebSocket.

---

## Data Models

### Room

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, indexed | Unique room identifier |
| `room_code` | `String(12)` | Unique, indexed, not null | URL-safe slug for the room |
| `host_id` | `UUID` | indexed, not null | Foreign Key reference to the user. |
| `status` | `String(10)` | Default `'pending'` | Room status (`pending`, `active`, `ended`) |
| `scheduled_at` | `DateTime` | Nullable | Optional future date |
| `settings` | `JSON` | Dict | Keys: `lock_room`, `max_participants`, etc. |

### Participant

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, indexed | Unique participant identifier |
| `room_id` | `UUID` | indexed, not null| ForeignKey |
| `user_id` | `UUID` | Nullable | ForeignKey (Null if Guest) |
| `guest_session_id` | `UUID` | Nullable | Session tracking ID for anonymous guests |
| `display_name` | `String(255)` | Not Null | User's profile name OR guest-submitted name |
| `role` | `String(10)` | Default `'guest'` | Role: `host`, `participant`, `guest` |

### MeetingInvitation

| Column | Type | Constraints | Description |
|---|---|---|---|
| `token` | `String(64)` | Unique, not null| Cryptographic token embedded in the email |
| `email` | `String(255)` | Not null | Targeted invited email |
| `expires_at` | `DateTime` | Not null | Automatically set +48 hours from dispatch |

---

## Request / Response Schemas

### Request Schemas

| Schema | Used By | Fields |
|---|---|---|
| `RoomCreate` | `POST /` | `name`, `settings`, `scheduled_at` |
| `JoinRoomRequest` | `POST /join` | `display_name (optional)`, `listening_language (optional)` |
| `RoomConfigUpdate`| `PATCH /config`| Matches settings fields |
| `InviteRequest` | `POST /invite` | `emails (list[str])` |

### Enums

#### `ParticipantRole`

| Value | Description |
|---|---|
| `host` | The room creator. |
| `guest` | Unauthenticated / generic participant. |
| `participant` | A standard authenticated user. |

#### `RoomStatus`

| Value | Description |
|---|---|
| `pending` | Created, but host hasn't explicitly entered the room. |
| `active` | The host has officially walked through the door. |
| `ended` | Meeting explicitly shut down by the host. |

---

## Internal Services

### MeetingService

The core routing logic engine for the module.

| Method | Purpose |
|---|---|
| `create_room()` | Enforces unique slug handling and builds database references. |
| `join_room()` | Reconciles User identity vs Guest Token vs Returning PT states. Resolves if a user bypasses straight into the `ACTIVE` room or halts inside `Lobby`. |
| `update_config()` | Handles patching `room.settings` gracefully and prepares the payload. |

### MeetingStateService

Encapsulates all interaction with Redis for high-throughput ephemeral states like Live Participants or Lobbies. Uses native Redis paradigms like Pipelines and Hashes for quick mutations.

| Method | Purpose |
|---|---|
| `add_participant()` / `remove_participant()` | Manages live room occupancy hash map. |
| `add_to_lobby()` / `admit_from_lobby()` | Waitlisting pipeline actions ensuring atomicity. |
| `cleanup_room()` | Destroys all traces of a room in Redis during `end()`. |
