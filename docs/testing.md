# Testing FluentMeet WebSockets via Postman

Because FluentMeet's real-time features rely on WebSockets, you can test the entire pipeline end-to-end using Postman before wiring up the frontend SDK.

## Prerequisites

1. Ensure the FluentMeet backend is running (`uvicorn app.main:app --reload`).
2. Ensure Kafka and Redis are running locally.
3. Ensure the Kafka Consumers (STT, translation, TTS) are running in the background.

## 1. Obtain Authentication Token & Room Code

First, create a meeting and join it to get an authentication token. You must actually "join" the room so that your participant state is set in Redis.

1. **REST Request**: `POST {{base_url}}/api/v1/meetings` (creates a room, returns `room_code`)
2. **REST Request**: `POST {{base_url}}/api/v1/meetings/{{room_code}}/join`
   - **Body**: `{ "listening_language": "es", "display_name": "Test User" }`
3. Extract your Bearer Token (either from the Guest token response or your registered user Login). For WebSockets, we will append it as a Query Parameter: `?token=YOUR_TOKEN`.

---

## 2. Test Signaling WebSocket

The Signaling WebSocket behaves like a Pub/Sub layer for WebRTC negotiation.

**Postman Setup**:
1. Click **New** -> **WebSocket**.
2. **URL**: `ws://localhost:8000/api/v1/ws/signaling/{{room_code}}?token={{token}}`
3. Click **Connect**.

**Actions to Test**:
1. Sending a broadcast (e.g. an Offer but no target ID):
   - In the Message box, write: `{"type": "offer", "sdp": "fake_sdp"}`
   - Click **Send**.
   - (You won't get it back because the server filters out messages from the sender. If you connect a *second* Postman tab with a different token/user, the second tab will receive it).

2. Unicasting (suppress original audio):
   - Send `{"type": "suppress_original", "target_user_id": "other-user-uuid"}`
   - The server uses Redis to route this exactly to that user.

---

## 3. Test Captions WebSocket

The Captions WebSocket is unidirectional. It receives events dynamically from Kafka.

**Postman Setup**:
1. Click **New** -> **WebSocket**.
2. **URL**: `ws://localhost:8000/api/v1/ws/captions/{{room_code}}?token={{token}}`
3. Click **Connect**.

**Actions to Test**:
1. Keep this connection open. You will not send anything into it.
2. When audio is sent to the Audio WebSocket (below), the AI pipeline will trigger `Transcriptions` and `Translations` to Kafka.
3. You will see JSON arrive here automatically containing the text payload:
   ```json
   {
       "event": "caption",
       "speaker_id": "...",
       "language": "es",
       "text": "Hola mundo",
       "is_final": true,
       "timestamp_ms": 1712123456789
   }
   ```

---

## 4. Test Audio WebSocket (Bidirectional)

The Audio WebSocket requires broadcasting Binary streams.

**Postman Setup**:
1. Click **New** -> **WebSocket**.
2. **URL**: `ws://localhost:8000/api/v1/ws/audio/{{room_code}}?token={{token}}`
3. Click **Connect**.

**Actions to Test**:
In Postman, WebSockets text messages represent Strings, but you must send **Binary** messages for audio payloads.

1. Generate a raw 16kHz PCM audio chunk file on your computer.
2. In the Postman WebSocket interface, next to the "Message" input field, choose **"Base64"** or **"Binary"** file input type.
3. Select your raw audio file and click **Send**.
4. The Backend will package it into `audio.raw`. It will cascade through `STTWorker` -> `TranslationWorker` -> `TTSWorker`.
5. Shortly after, your Postman Audio WebSocket will receive a **Binary frame**. This is the translated synthesized audio stream returned by Kafka!
6. If you have the Captions WebSocket still open in another tab, you will see the captions flash simultaneously.
