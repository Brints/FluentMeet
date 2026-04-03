### Feature: Implement Real-Time WebSocket Audio Streaming & Live Captions

**Problem**
FluentMeet's core meeting experience depends on participants hearing translated speech and reading live captions with minimal latency. Currently there is no WebSocket layer to bridge the frontend WebRTC audio stream with the backend Kafka AI pipeline, and no mechanism to route translated audio back to the correct participants based on their language preference. Without this, the real-time translation pipeline — even when fully built — has no way to receive input or deliver output to meeting participants.

**Proposed Solution**
Implement three WebSocket endpoints that serve as the real-time gateway between the frontend and the Kafka-backed AI pipeline:

1. `/ws/audio/{room_id}` — bidirectional audio channel: receives raw audio chunks from participants and streams translated audio back.
2. `/ws/captions/{room_id}` — unidirectional caption broadcast: pushes real-time transcribed and translated text to all room subscribers.
3. `/ws/signaling/{room_id}` — WebRTC signaling channel for Offer/Answer/ICE candidate exchange.

An SFU-lite routing layer will ensure each participant receives only the audio translated into *their* listening language, rather than a broadcast of all streams.

**User Stories**
*   **As a meeting participant,** I want to hear the speaker's translated voice within 500ms of them speaking, so the conversation feels natural and uninterrupted.
*   **As a meeting participant,** I want to see live captions in my own language appear in real-time alongside the translated audio, so I can follow the conversation even in noisy environments.
*   **As a participant who speaks Language A and listens in Language B,** I want the original Language A audio to be suppressed and replaced with the Language B synthesis, so I am not hearing both streams simultaneously.
*   **As a developer,** I want WebSocket connections to be authenticated and room-scoped, so only legitimate participants in a given room can send or receive audio.

**Acceptance Criteria**
1.  `GET /ws/audio/{room_id}` upgrades to a WebSocket and:
    *   Authenticates the connecting user via a query-parameter token before the upgrade completes.
    *   Accepts binary audio frames and publishes them to the `audio.raw` Kafka topic with `room_id`, `user_id`, and a monotonically increasing `sequence_number`.
    *   Subscribes to the `audio.synthesized` Kafka topic filtered by `room_id` and `target_language` matching the user's `listening_language`, and streams synthesized audio frames back to the client.
2.  `GET /ws/captions/{room_id}` upgrades to a WebSocket and:
    *   Broadcasts all `text.original` and `text.translated` messages for the room in real-time as structured JSON: `{ "speaker_id", "language", "text", "is_final" }`.
3.  `GET /ws/signaling/{room_id}` upgrades to a WebSocket and:
    *   Relays WebRTC Offer, Answer, and ICE Candidate messages between peers in the same room.
4.  **Original Audio Suppression**: When a participant's synthesized audio is ready, a signaling message (`{ "type": "suppress_original", "speaker_id": "..." }`) is sent over the signaling WebSocket so the client can mute the original WebRTC track.
5.  A `ConnectionManager` in `app/services/connection_manager.py` tracks all active WebSocket connections per room and handles clean disconnection.
6.  All WebSocket endpoints require a valid JWT; unauthenticated connections are rejected with `WS 4001 Unauthorized` before the upgrade.
7.  End-to-end latency (audio sent → translated audio received) is logged per frame.

**Proposed Technical Details**
*   **WebSocket Handlers**: Implemented in `app/api/v1/endpoints/ws.py` using FastAPI's `WebSocket` class.
*   **Connection Manager**: `app/services/connection_manager.py` — a singleton that maps `room_id → { user_id → WebSocket }` stored in memory (per instance). For multi-instance deployments, connection state is synchronized via a Redis Pub/Sub channel keyed by `room_id`.
*   **Kafka Integration**: Each accepted audio WebSocket spawns two async tasks: one for ingesting (WS → `audio.raw`) and one for egress (`audio.synthesized` → WS).
*   **Authentication**: Token passed as a query parameter (`?token=<access_token>`) since browser WebSocket APIs do not support custom headers. The token is validated using the existing `get_current_user` dependency before the upgrade.
*   **Audio Frame Format**: Binary WebSocket frames carrying raw PCM audio at 16kHz mono, matching the Deepgram STT input requirements.
*   **Caption Message Schema**:
    ```json
    {
      "event": "caption",
      "speaker_id": "user-uuid",
      "language": "es",
      "text": "Hola, ¿cómo estás?",
      "is_final": true,
      "timestamp_ms": 1710419000000
    }
    ```

**Tasks**
- [ ] Implement `ConnectionManager` in `app/services/connection_manager.py` with Redis Pub/Sub for multi-instance room state.
- [ ] Implement `/ws/audio/{room_id}` with JWT auth, Kafka producer (ingest), and Kafka consumer (egress) as concurrent async tasks.
- [ ] Implement `/ws/captions/{room_id}` to broadcast `text.original` and `text.translated` Kafka messages to all room subscribers.
- [ ] Implement `/ws/signaling/{room_id}` for WebRTC Offer/Answer/ICE relay.
- [ ] Implement the `Original Audio Suppression` signaling message dispatched when synthesized audio is ready for a given speaker.
- [ ] Add JWT query-parameter authentication to all WebSocket endpoints; return `WS 4001` on failure.
- [ ] Register all WebSocket routes in `app/api/v1/api.py`.
- [ ] Add per-frame latency logging (ingest timestamp → egress timestamp).
- [ ] Write unit tests for `ConnectionManager` (connect, disconnect, broadcast).
- [ ] Write integration tests for the `/ws/audio` ingest → Kafka publish flow (mock Kafka).

**Open Questions/Considerations**
*   How should the system handle a participant joining a room mid-conversation — should they receive a buffer of recent captions or only see captions from the moment they join?
*   For the multi-instance `ConnectionManager`, Redis Pub/Sub is proposed — should we instead use a dedicated WebSocket broker like Centrifuge or Soketi?
*   What happens when a Kafka consumer for the egress falls behind — should we skip stale audio frames to maintain low latency, or deliver all frames in order?
*   Should the audio frame size (chunk duration) be configurable, or fixed at a value optimal for Deepgram (e.g., 250ms chunks)?