"""Voice.ai WebSocket Multi-Context TTS streaming client.

Manages a persistent WebSocket connection to Voice.ai's Multi-Context
endpoint (wss://dev.voice.ai/api/v1/tts/multi-stream) for low-latency,
concurrent text-to-speech synthesis across multiple participants.

API Reference: https://voice.ai/docs/api-reference/text-to-speech/multi-context-websocket
"""

import asyncio
import base64
import contextlib
import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

import websockets
from websockets.exceptions import (
    ConnectionClosed,
    ConnectionClosedError,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

# Map our internal encoding names to Voice.ai audio_format values
_FORMAT_MAP = {
    "linear16": "pcm_24000",
    "opus": "opus_48000_64",
}

# Maximum reconnection attempts before giving up.
_MAX_RECONNECT_ATTEMPTS = 3


class VoiceAIWebSocketTTS:
    """Persistent WebSocket connection to Voice.ai Multi-Context TTS.

    Supports multiple concurrent TTS streams over a single connection,
    each identified by a unique ``context_id``. Audio chunks are yielded
    in the same ``{audio_bytes, sample_rate}`` dict format used by
    ``VoiceAITTSService.synthesize_stream()``.

    Attributes:
        _ws: The active WebSocket connection, or None.
        _connected: Whether the WebSocket is currently open.
    """

    def __init__(self, ping_interval: float = 20.0) -> None:
        """Initialize the Voice.ai WebSocket TTS client.

        Args:
            ping_interval: Seconds between WebSocket keepalive pings.
        """
        self._ping_interval = ping_interval
        self._ws: Any = None
        self._connected = False
        self._connect_lock = asyncio.Lock()
        self._context_queues: dict[str, asyncio.Queue] = {}
        self._reader_task: asyncio.Task | None = None

    async def connect(self) -> None:
        """Establish the WebSocket connection to Voice.ai multi-stream."""
        if self._connected and self._ws and not self._ws.closed:
            return

        async with self._connect_lock:
            # Double-check after acquiring lock
            if self._connected and self._ws and not self._ws.closed:
                return

            if not settings.VOICE_AI_API_KEY:
                raise RuntimeError("VOICE_AI_API_KEY is not configured.")

            ws_url = settings.VOICEAI_WS_URL
            headers = {
                "Authorization": f"Bearer {settings.VOICE_AI_API_KEY}",
            }

            logger.info("Connecting to Voice.ai WebSocket TTS at %s", ws_url)

            self._ws = await websockets.connect(
                ws_url,
                additional_headers=headers,
                ping_interval=self._ping_interval,
                ping_timeout=10.0,
                close_timeout=5.0,
            )
            self._connected = True
            # Reset/clear queues (though normally empty on a new connection)
            self._context_queues = {}
            # Start background reader task
            self._reader_task = asyncio.create_task(self._reader_loop())
            logger.info("Voice.ai WebSocket TTS connected, reader loop started")

    async def close(self) -> None:
        """Gracefully close the WebSocket connection."""
        self._connected = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                logger.warning("Error closing Voice.ai WebSocket: %s", e)
            self._ws = None
        if self._reader_task:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None
        logger.info("Voice.ai WebSocket TTS connection closed")

    async def _ensure_connected(self) -> None:
        """Ensure the WebSocket is connected, reconnecting if needed."""
        if not self._connected or not self._ws or self._ws.closed:
            await self.connect()

    async def _reconnect_with_backoff(self) -> None:
        """Attempt reconnection with exponential backoff."""
        self._connected = False
        if self._ws:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None

        for attempt in range(1, _MAX_RECONNECT_ATTEMPTS + 1):
            backoff = min(2**attempt, 10)
            logger.warning(
                "Voice.ai WebSocket reconnect attempt %d/%d (backoff=%.1fs)",
                attempt,
                _MAX_RECONNECT_ATTEMPTS,
                backoff,
            )
            await asyncio.sleep(backoff)
            try:
                await self.connect()
                logger.info("Voice.ai WebSocket reconnected on attempt %d", attempt)
                return
            except Exception as e:
                logger.error(
                    "Voice.ai WebSocket reconnect attempt %d failed: %s",
                    attempt,
                    e,
                )

        raise ConnectionError(
            f"Voice.ai WebSocket reconnection exhausted "
            f"({_MAX_RECONNECT_ATTEMPTS} attempts)"
        )

    async def _reader_loop(self) -> None:
        """Background task that reads messages from the WebSocket and routes them."""
        logger.info("Voice.ai WebSocket reader loop started")
        try:
            async for message in self._ws:
                if isinstance(message, str):
                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Voice.ai WS reader: non-JSON text frame: %s",
                            message[:200],
                        )
                        continue

                    context_id = data.get("context_id")
                    if not context_id:
                        logger.warning(
                            "Voice.ai WS reader: message missing context_id: %s",
                            message[:200],
                        )
                        continue

                    # Route to the appropriate context's queue
                    queue = self._context_queues.get(context_id)
                    if queue:
                        await queue.put(data)
                    else:
                        logger.debug(
                            "Voice.ai WS reader: no active queue for context %s",
                            context_id,
                        )
                else:
                    logger.warning(
                        "Voice.ai WS reader: received unexpected binary frame"
                    )
        except (ConnectionClosed, ConnectionClosedError) as e:
            logger.info("Voice.ai WebSocket connection closed in reader loop: %s", e)
        except Exception as e:
            logger.error("Voice.ai WebSocket reader loop error: %s", e, exc_info=True)
        finally:
            self._connected = False
            # Distribute connection closed error to all active queues to prevent hangs
            for context_id, queue in list(self._context_queues.items()):
                try:
                    await queue.put(
                        {
                            "error": "WebSocket connection lost/closed in reader loop",
                            "disconnected": True,
                            "context_id": context_id,
                        }
                    )
                except Exception as put_err:
                    logger.warning(
                        "Failed to put disconnect event in queue for %s: %s",
                        context_id,
                        put_err,
                    )
            logger.info("Voice.ai WebSocket reader loop terminated")

    def _get_stream_params(self, encoding: str, language: str) -> tuple[str, int, str]:
        """Determine audio format, sample rate, and model for streaming."""
        audio_format = _FORMAT_MAP.get(encoding, "pcm_24000")

        # Determine sample rate from the format string
        sample_rate = 16000
        if "24000" in audio_format:
            sample_rate = 24000
        elif "48000" in audio_format:
            sample_rate = 48000

        # Select model: multilingual for non-English, standard for English
        model = settings.VOICEAI_TTS_MODEL
        if language == "en" and "multilingual" in model:
            model = model.replace("multilingual-", "")

        return audio_format, sample_rate, model

    async def _send_init_and_flush(
        self,
        context_id: str,
        model: str,
        language: str,
        audio_format: str,
        voice_id: str | None,
        text: str,
    ) -> None:
        """Send initialization and flush messages to Voice.ai WebSocket."""
        # 1. Send initialization + text message
        init_msg: dict[str, Any] = {
            "context_id": context_id,
            "model": model,
            "language": language,
            "audio_format": audio_format,
            "delivery_mode": settings.VOICEAI_DELIVERY_MODE,
            "text": text,
            "temperature": 1,
            "top_p": 0.8,
        }
        if voice_id:
            init_msg["voice_id"] = voice_id

        await self._ws.send(json.dumps(init_msg))

        # 2. Send flush to trigger synthesis and request auto-close of context
        flush_msg = {
            "context_id": context_id,
            "flush": True,
            "auto_close": True,
        }
        await self._ws.send(json.dumps(flush_msg))

    async def synthesize_stream(
        self,
        text: str,
        *,
        context_id: str,
        language: str = "en",
        voice_id: str | None = None,
        encoding: str = "linear16",
    ) -> AsyncGenerator[dict, None]:
        """Stream TTS audio chunks via Voice.ai WebSocket multi-stream.

        Args:
            text: The text to synthesize.
            context_id: Unique identifier for this TTS stream.
            language: ISO 639-1 language code. Defaults to "en".
            voice_id: Optional Voice.ai voice ID.
            encoding: Output encoding ("linear16" or "opus").
                Defaults to "linear16".

        Yields:
            dict: A dictionary containing "audio_bytes" and "sample_rate".
        """
        audio_format, sample_rate, model = self._get_stream_params(encoding, language)

        await self._ensure_connected()

        # Create and register a queue for this context
        queue: asyncio.Queue = asyncio.Queue()
        self._context_queues[context_id] = queue

        start = time.monotonic()

        try:
            await self._send_init_and_flush(
                context_id=context_id,
                model=model,
                language=language,
                audio_format=audio_format,
                voice_id=voice_id,
                text=text,
            )

            elapsed_ms = (time.monotonic() - start) * 1000
            logger.debug(
                "Voice.ai WS TTS init+flush sent in %.1fms "
                "context=%s lang=%s format=%s",
                elapsed_ms,
                context_id,
                language,
                audio_format,
            )

            # 3. Read messages routed to our queue
            while True:
                data = await queue.get()

                if data.get("disconnected"):
                    raise ConnectionError(data.get("error", "WebSocket disconnected"))

                if "audio" in data:
                    audio_b64 = data["audio"]
                    audio_bytes = base64.b64decode(audio_b64)
                    yield {
                        "audio_bytes": audio_bytes,
                        "sample_rate": sample_rate,
                    }

                if data.get("is_last"):
                    total_ms = (time.monotonic() - start) * 1000
                    logger.debug(
                        "Voice.ai WS TTS completed context=%s in %.1fms",
                        context_id,
                        total_ms,
                    )
                    break

                if "error" in data:
                    logger.error(
                        "Voice.ai WS TTS error context=%s: %s",
                        context_id,
                        data["error"],
                    )
                    raise RuntimeError(f"Voice.ai WS TTS error: {data['error']}")

        except Exception as e:
            logger.warning(
                "Voice.ai WebSocket error during synthesis context=%s: %s",
                context_id,
                e,
            )
            # If we encountered a connection error, trigger a reconnect
            if isinstance(
                e, (ConnectionClosed, ConnectionClosedError, ConnectionError)
            ):
                await self._reconnect_with_backoff()
            raise
        finally:
            # Unregister the context queue
            self._context_queues.pop(context_id, None)


# ── Module-level singleton ────────────────────────────────────────────
_ws_tts_service: VoiceAIWebSocketTTS | None = None


def get_voiceai_ws_tts_service() -> VoiceAIWebSocketTTS:
    global _ws_tts_service  # noqa: PLW0603
    if _ws_tts_service is None:
        _ws_tts_service = VoiceAIWebSocketTTS()
    return _ws_tts_service
