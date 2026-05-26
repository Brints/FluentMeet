# FluentMeet Deepgram Integration Documentation

> **Package Location:** `/app/external_services/deepgram`
> **Purpose:** Handles external asynchronous integrations with the Deepgram Speech-to-Text API for both batch and real-time streaming transcriptions.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Batch Service (`service.py`)](#batch-service-servicepy)
  - [`DeepgramSTTService`](#deepgramsttservice)
  - [`transcribe()`](#transcribeaudio_bytes-language-sample_rate-encoding)
- [WebSocket Streaming Service (`streaming.py`)](#websocket-streaming-service-streamingpy)
  - [`DeepgramStreamingSTT`](#deepgramstreamingstt)
  - [`connect()`](#connect)
  - [`send_audio()`](#send_audioaudio_bytes)
  - [`close()`](#close)
  - [`_reconnect()`](#_reconnect)
- [Configuration](#configuration)

---

## Overview

The `app/external_services/deepgram` package wraps both the Deepgram REST `/v1/listen` endpoint (for batch fallback mode) and the Deepgram WebSocket streaming API (for continuous real-time speech-to-text).

It supports two modes:
1. **Batch STT** (`DeepgramSTTService`) — Processes buffered audio chunks via `POST` requests.
2. **Streaming STT** (`DeepgramStreamingSTT`) — Opens persistent WebSocket connections for ultra-low latency live transcription, yielding interim and final results in real-time.

---

## Architecture

This package exposes:
*   `DeepgramSTTService` (HTTP batch wrapper, singleton)
*   `DeepgramStreamingSTT` (WebSocket streaming connection wrapper, instance-per-user-session)

The services are actively used by the `STTWorker` consumer daemon listening to Kafka `audio.raw`.

---

## Batch Service (`service.py`)

### `DeepgramSTTService`

A stateless service wrapping the Deepgram HTTP REST endpoint.

**Singleton accessor:** `get_deepgram_stt_service()`

#### `transcribe(audio_bytes, language, sample_rate, encoding)`
Sends a block of audio data to Deepgram.
*   **Args:**
    *   `audio_bytes` *(bytes)*: Standard PCM binary string or OPUS stream bytes.
    *   `language` *(str)*: A localized ISO 639-1 code hint (e.g., `"en"`).
    *   `sample_rate` *(int)*: Standard `16000` (Hz).
    *   `encoding` *(str)*: Tells Deepgram the format (`"linear16"` or `"opus"`).
*   **Returns:**
    ```json
    {
      "text": "Hello world",
      "confidence": 0.99,
      "detected_language": "en",
      "latency_ms": 32.5
    }
    ```
*   **Exception Behavior:** Raises `httpx.HTTPStatusError` on non-2xx codes to trigger worker retry/circuit-breaking.

---

## WebSocket Streaming Service (`streaming.py`)

### `DeepgramStreamingSTT`

An instance-based client wrapping Deepgram's SDK WebSocket client (`AsyncV1SocketClient`) to enable persistent, real-time transcription.

#### `__init__(api_key, room_id, user_id, on_transcript, language, model, sample_rate)`
Initializes the client.
*   **Args:**
    *   `api_key` *(str)*: Deepgram API key.
    *   `room_id` *(str)*: The room identifier.
    *   `user_id` *(str)*: The user identifier.
    *   `on_transcript` *(async callable)*: Callback invoked on receiving a transcript, signature `on_transcript(text, is_final, confidence)`.
    *   `language` *(str)*: Language code hint (e.g., `"en"`).
    *   `model` *(str)*: Deepgram model name. Defaults to `"nova-2"`.
    *   `sample_rate` *(int)*: Sample rate in Hz. Defaults to `16000`.

#### `connect()`
Establishes the WebSocket connection via the Deepgram SDK.
*   Uses `settings.DEEPGRAM_INTERIM_RESULTS` to request interim/final results.
*   Uses `settings.DEEPGRAM_ENDPOINTING_MS` to define silence threshold before endpointing.
*   Registers event handlers for `MESSAGE`, `ERROR`, and `CLOSE`.
*   Starts a background listen task and keepalive ping loop.

#### `send_audio(audio_bytes)`
Streams raw audio chunk bytes directly to Deepgram over the open connection.
*   **Args:**
    *   `audio_bytes` *(bytes)*: Raw PCM/OPUS audio chunk.

#### `close()`
Gracefully sends a closing signal to Deepgram and closes all associated background tasks and connection contexts.

#### `_reconnect()`
Private helper that implements automatic reconnection with exponential backoff if the WebSocket disconnects unexpectedly.
*   Retries up to 3 times with exponential backoff (2s, 4s, 8s).

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEEPGRAM_API_KEY` | `None` | API key for Deepgram authentication |
| `DEEPGRAM_STREAMING_URL` | `"wss://api.deepgram.com/v1/listen"` | WebSocket endpoint URL (handled via SDK) |
| `DEEPGRAM_INTERIM_RESULTS` | `True` | Whether to request interim transcription events |
| `DEEPGRAM_ENDPOINTING_MS` | `300` | Silence threshold in ms before deepgram endpoints a sentence |
| `DEEPGRAM_USE_STREAMING` | `True` | Feature flag to switch between streaming and batch STT |
