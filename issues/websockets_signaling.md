### Feature: Implement WebSocket Endpoints — Signaling, Audio & Captions

**Problem**
The FluentMeet real-time translation pipeline is built but has no WebSocket layer to connect frontend clients to it. Without these three endpoints, clients cannot perform WebRTC negotiation, stream audio for translation, or receive live captions. The high-level architecture is defined in the [Real-Time Audio issue](./realtime_audio.md); this issue captures the concrete implementation spec for each endpoint.

**Proposed Solution**
Implement three FastAPI WebSocket endpoints in `app/api/v1/endpoints/ws.py`:
1. **`/ws/signaling/{room_code}`** — routes WebRTC Offer/Answer/ICE messages between peers in the same room.
2. **`/ws/audio/{room_code}`** — bidirectional: ingests raw audio from participants into Kafka (`audio.raw`) and streams translated audio back from Kafka (`audio.synthesized`) filtered by the user's `listening_language`.
3. **`/ws/captions/{room_code}`** — pushes live transcription and translation events from Kafka (`text.original`, `text.translated`) to all room subscribers.

All three endpoints authenticate via a JWT `?token=<access_token>` query parameter (browser WebSocket APIs do not support custom headers).

**User Stories**
*   **As a meeting participant,** I want my browser to negotiate a WebRTC connection through the signaling WebSocket, so peer audio tracks are established without manual configuration.
*   **As a participant,** I want my audio to be sent to the server for real-time translation and the synthesised response streamed back to me, so I hear the speaker in my listening language.
*   **As a participant,** I want live captions to appear in near-real-time as speakers talk, so I can follow the conversation visually even in noisy environments.

---

### WS /ws/signaling/{room_code}

**Acceptance Criteria**
1.  On connection: validates JWT `?token=`; rejects with `WS 4001` if invalid. Verifies the user is a participant of the room; rejects with `WS 4003` if not.
2.  Registers the connection in `ConnectionManager` under `room_code`.
3.  Forwards all received JSON messages to all other connections in the same room (peer-to-peer relay). Expected message types:
    ```json
    { "type": "offer",     "sdp": "...",  "target_user_id": "uuid" }
    { "type": "answer",    "sdp": "...",  "target_user_id": "uuid" }
    { "type": "ice_candidate", "candidate": "...", "target_user_id": "uuid" }
    { "type": "suppress_original", "speaker_id": "uuid" }
    ```
4.  On disconnect: removes the connection from `ConnectionManager` and broadcasts a `{ "type": "peer_left", "user_id": "..." }` event to remaining participants.

---

### WS /ws/audio/{room_code}

**Acceptance Criteria**
1.  On connection: validates JWT and room membership (same as signaling). Reads `current_user.listening_language` to determine which synthesised audio stream to subscribe to.
2.  Spawns two concurrent async tasks:
    *   **Ingest task**: reads binary audio frames from the WebSocket and publishes to Kafka topic `audio.raw` with envelope:
        ```json
        { "room_code": "abc123", "user_id": "uuid", "sequence": 42, "correlation_id": "uuid", "payload": "<base64 or raw bytes>" }
        ```
    *   **Egress task**: consumes from Kafka topic `audio.synthesized`, filtered by `room_code` and `target_language == user.listening_language`, and writes binary frames back to the WebSocket.
3.  Both tasks are cancelled on WebSocket disconnect, and Kafka consumer offsets are committed.
4.  Stale audio frames (where `sequence` is more than 10 behind the latest received) are **dropped** to maintain low latency rather than delivered out of order.
5.  Per-frame latency (publish timestamp → egress timestamp) is logged at `DEBUG` level using the `correlation_id`.

---

### WS /ws/captions/{room_code}

**Acceptance Criteria**
1.  On connection: validates JWT and room membership.
2.  Subscribes to Kafka topics `text.original` and `text.translated`, filtered by `room_code`.
3.  Forwards each consumed message to the WebSocket client as JSON:
    ```json
    {
      "event": "caption",
      "speaker_id": "uuid",
      "language": "en",
      "text": "Hello, how are you?",
      "is_final": true,
      "timestamp_ms": 1710419000000
    }
    ```
4.  `is_final: false` messages are partial transcripts (sent during speech); `is_final: true` marks the end of a sentence.
5.  The Kafka consumer uses a **dedicated consumer group** (`captions-{room_code}-{user_id}`) so each participant receives their own independent stream (no offset sharing between participants).
6.  On disconnect: consumer is closed and the consumer group is cleaned up.

---

**Proposed Technical Details**
*   **File**: `app/api/v1/endpoints/ws.py` [NEW] — all three WebSocket route handlers.
*   **Authentication**: shared `authenticate_ws(token: str, db) -> User` helper that decodes the JWT and returns the `User`, raising `WebSocketException(code=4001)` on failure.
*   **Room Guard**: shared `assert_room_participant(room_code, user_id, db)` helper; raises `WebSocketException(code=4003)` if user is not in the room.
*   **ConnectionManager**: `app/services/connection_manager.py` (defined in [Real-Time Audio issue](./realtime_audio.md)) — `connect`, `disconnect`, `broadcast_to_room`, `send_to_user`.
*   **Kafka**: `aiokafka.AIOKafkaProducer` for ingest; `aiokafka.AIOKafkaConsumer` per connection for egress and captions.
*   **New/Modified Files**:
    *   `app/api/v1/endpoints/ws.py` [NEW]
    *   `app/api/v1/api.py` — register WS router [MODIFY]

**Tasks**
- [ ] Implement shared `authenticate_ws` and `assert_room_participant` helpers.
- [ ] Implement `WS /ws/signaling/{room_code}` with peer message relay and disconnect broadcast.
- [ ] Implement `WS /ws/audio/{room_code}` with concurrent ingest and egress async tasks.
- [ ] Implement stale frame dropping logic in the audio egress task.
- [ ] Implement `WS /ws/captions/{room_code}` with per-user consumer group.
- [ ] Register all WebSocket routes in `app/api/v1/api.py`.
- [ ] Write unit tests for `authenticate_ws` and `assert_room_participant`.
- [ ] Write integration tests for signaling relay, audio ingest → Kafka, and caption broadcast (mock Kafka).

**Open Questions/Considerations**
*   Should the signaling WebSocket route messages only to the `target_user_id` (unicast) or broadcast to all room members? Unicast is more correct for WebRTC but requires `ConnectionManager` to support targeted delivery.
*   For the audio egress, should stale frame detection use a sequence number threshold (as proposed) or a timestamp age threshold (e.g., drop frames older than 500ms)?
*   Should `WS /ws/captions/{room_code}` also replay the last N caption messages on connect, so a participant who briefly disconnects and reconnects does not miss context?
