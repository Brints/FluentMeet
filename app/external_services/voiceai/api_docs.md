# FluentMeet Voice.ai Integration Documentation

> **Package Location:** `/app/external_services/voiceai`
> **Purpose:** Handles external asynchronous integrations with the Voice.ai Text-to-Speech Generation API.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [HTTP Service (`service.py`)](#http-service-servicepy)
  - [`VoiceAITTSService`](#voiceattsservice)
  - [`synthesize()`](#synthesizetext-language-voice_id-encoding)
  - [`synthesize_stream()`](#synthesize_streamtext-language-voice_id-encoding)
- [WebSocket Service (`websocket_streaming.py`)](#websocket-service-websocket_streamingpy)
  - [`VoiceAIWebSocketTTS`](#voiceaiwebsockettts)
  - [`connect()`](#connect)
  - [`synthesize_stream()`](#synthesize_streamtext-context_id-language-voice_id-encoding)
  - [`close()`](#close)
- [Format & Model Targeting](#format--model-targeting)
- [Configuration](#configuration)
- [Feature Flags](#feature-flags)

---

## Overview

The `app/external_services/voiceai` package acts as the active backend for stage 4 of the real-time audio pipeline. It intercepts translated text streams and synthesizes them into dynamic real-time human voices using the Voice.ai TTS endpoints. This package runs dynamically as an alternative to OpenAI depending on standard environment configurations (`ACTIVE_TTS_PROVIDER="voiceai"`).

Two transport mechanisms are available:

1. **HTTP** (`VoiceAITTSService`) — Batch POST and chunked HTTP streaming.
2. **WebSocket** (`VoiceAIWebSocketTTS`) — Persistent connection via the Multi-Context WebSocket API, supporting multiple concurrent TTS streams over a single connection.

---

## Architecture

Both services maintain tight coupling with core architectures and follow identical conventions: singleton pattern, `_FORMAT_MAP` encoding resolution, model selection logic, and unified `dict` output format.

The HTTP service resolves all remote calls using `httpx.AsyncClient`. The WebSocket service maintains a persistent connection via the `websockets` library, with auto-reconnection and keepalive/ping handling.

Configuration relies on environment variables, pulling `VOICEAI_TTS_MODEL` and provider-specific settings per-request.

---

## HTTP Service (`service.py`)

### `VoiceAITTSService`

Fully asynchronous service layer encapsulated via singleton pattern, mapping logic to Voice.ai REST endpoints.

**Singleton accessor:** `get_voiceai_tts_service()`

#### `synthesize(text, language, voice_id, encoding)`

Converts text to audio bytes via the Voice.ai batch TTS endpoint (`POST /api/v1/tts/speech`).

*   **Args:**
    *   `text` *(str)*: The text to synthesize.
    *   `language` *(str)*: ISO 639-1 language code. Defaults to `"en"`.
    *   `voice_id` *(str | None)*: Optional Voice.ai voice ID for custom cloned models. Uses default if `None`.
    *   `encoding` *(str)*: Output encoding (`"linear16"` or `"opus"`). Defaults to `"linear16"`.
*   **Returns:**
    ```json
    {
      "audio_bytes": "<binary>",
      "sample_rate": 24000,
      "latency_ms": 352.1
    }
    ```
*   **Exceptions:** Raises `httpx.HTTPStatusError` on non-2xx responses.

#### `synthesize_stream(text, language, voice_id, encoding)`

Streams TTS audio chunks via the Voice.ai HTTP streaming endpoint (`POST /api/v1/tts/speech/stream`).

*   **Args:** Same as `synthesize()`.
*   **Yields:**
    ```json
    {
      "audio_bytes": "<binary chunk>",
      "sample_rate": 24000
    }
    ```
*   **Chunk size:** 4096 bytes per iteration.

---

## WebSocket Service (`websocket_streaming.py`)

### `VoiceAIWebSocketTTS`

Persistent WebSocket service for streaming TTS via the Voice.ai Multi-Context API (`wss://dev.voice.ai/api/v1/tts/multi-stream`). Supports multiple concurrent synthesis contexts multiplexed over a single connection.

**Singleton accessor:** `get_voiceai_ws_tts_service()`

#### `connect()`

Establishes or re-establishes the WebSocket connection.

*   Authenticates via `Authorization: Bearer <API_KEY>` header on handshake.
*   Retries up to 3 times with exponential backoff (1s, 2s, 4s).
*   Configures ping/pong keepalive (20s interval, 10s timeout).
*   **Exceptions:** Raises `websockets.exceptions.WebSocketException` if all attempts fail.

#### `synthesize_stream(text, context_id, language, voice_id, encoding)`

Streams TTS audio chunks via the WebSocket connection.

*   **Concurrency & Queue-Routing**: The service runs a single persistent connection. To support concurrent streams without collisions, a background `_reader_loop` task reads all JSON frames from the WebSocket and routes them to a specific `asyncio.Queue` registered for each `context_id`.
*   **Message flow:**
    1. Sends init JSON: `{"context_id": "...", "model": "...", "language": "...", "audio_format": "pcm_24000", "delivery_mode": "paced", "text": "...", "voice_id": "..."}`
    2. Sends flush + auto_close JSON: `{"context_id": "...", "flush": true, "auto_close": true}`
    3. Receives JSON audio frames: `{"audio": "<base64_encoded_pcm_data>", "context_id": "..."}` which are decoded back to raw binary bytes.
    4. Receives completion signal: `{"context_id": "...", "is_last": true}` when synthesis for that context finishes.
*   **Args:**
    *   `text` *(str)*: The text to synthesize.
    *   `context_id` *(str)*: Unique identifier for this synthesis context.
    *   `language` *(str)*: ISO 639-1 language code. Defaults to `"en"`.
    *   `voice_id` *(str | None)*: Optional Voice.ai voice ID.
    *   `encoding` *(str)*: Output encoding (`"linear16"` or `"opus"`). Defaults to `"linear16"`.
*   **Yields:**
    ```json
    {
      "audio_bytes": "<binary chunk>",
      "sample_rate": 24000
    }
    ```

#### `close()`

Closes the WebSocket connection gracefully with close code `1000`.

### WebSocket Close Codes

| Code | Meaning |
|------|---------|
| `1000` | Normal closure |
| `1007` | Validation error (invalid payload) |
| `1008` | Authentication failure or insufficient credits |

---

## Format & Model Targeting

### Format Resolution (`_FORMAT_MAP`)

Both services use an identical format mapping:

| Internal Encoding | Voice.ai `audio_format` | Sample Rate |
|-------------------|------------------------|-------------|
| `"linear16"` | `"pcm_24000"` | 24000 Hz |
| `"opus"` | `"opus_48000_64"` | 48000 Hz |

### Model Adjustments

Voice.ai supports multiple models. If `VOICEAI_TTS_MODEL` is set to a multilingual variant (e.g., `"voiceai-tts-multilingual-v1-latest"`) but the target `language` is `"en"`, both services automatically strip the `"multilingual-"` prefix to use the faster specialized English model.

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VOICE_AI_API_KEY` | `None` | API key for Voice.ai authentication |
| `VOICEAI_TTS_MODEL` | `"voiceai-tts-multilingual-v1-latest"` | TTS model identifier |
| `VOICEAI_TTS_API_URL` | `"https://dev.voice.ai/api/v1/tts/speech"` | HTTP batch endpoint |
| `VOICEAI_TTS_STREAM_URL` | `"https://dev.voice.ai/api/v1/tts/speech/stream"` | HTTP streaming endpoint |
| `VOICEAI_WS_URL` | `"wss://dev.voice.ai/api/v1/tts/multi-stream"` | WebSocket endpoint |
| `VOICEAI_DELIVERY_MODE` | `"paced"` | WebSocket delivery mode (`"paced"` or `"raw"`) |
| `VOICEAI_USE_STREAMING` | `True` | Enable HTTP chunked streaming |
| `VOICEAI_USE_WEBSOCKET` | `False` | Enable WebSocket streaming |
| `ACTIVE_TTS_PROVIDER` | `"openai"` | Active TTS provider (`"openai"` or `"voiceai"`) |

### `get_voiceai_headers()` (`config.py`)

Generates authentication headers for Voice.ai API requests.

*   Returns: `{"Authorization": "Bearer <API_KEY>", "Content-Type": "application/json"}`
*   Raises `RuntimeError` if `VOICE_AI_API_KEY` is not configured.

---

## Feature Flags

The TTS worker selects the transport mode using these priority rules:

1. **WebSocket** — `ACTIVE_TTS_PROVIDER="voiceai"` AND `VOICEAI_USE_WEBSOCKET=True`
2. **HTTP Streaming** — `ACTIVE_TTS_PROVIDER="voiceai"` AND `VOICEAI_USE_STREAMING=True` AND `VOICEAI_USE_WEBSOCKET=False`
3. **HTTP Batch** — All other cases (default for OpenAI, or Voice.ai with both streaming flags disabled)

WebSocket mode takes precedence over HTTP streaming when both are enabled.
