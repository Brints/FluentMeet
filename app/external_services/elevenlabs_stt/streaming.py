"""ElevenLabs Speech-to-Text WebSocket streaming client.

Connects to ElevenLabs scribe_v2_realtime WebSocket endpoint using raw websockets
to support real-time audio transcription.
"""

import asyncio
import base64
import contextlib
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import websockets
from websockets.client import WebSocketClientProtocol  # type: ignore[attr-defined]

from app.core.config import settings
from app.external_services.elevenlabs_stt.config import get_stt_language_code

logger = logging.getLogger(__name__)

# Maximum number of automatic reconnection attempts before giving up.
_MAX_RECONNECT_ATTEMPTS = 3


class ElevenLabsStreamingSTT:
    """Wrapper around ElevenLabs Scribe Real-time WebSocket connection for live STT."""

    def __init__(
        self,
        api_key: str,
        room_id: str,
        user_id: str,
        on_transcript: Callable[[str, bool, float], Coroutine[Any, Any, None]],
        language: str = "en",
        model: str = "scribe_v2_realtime",
        sample_rate: int = 24000,
    ) -> None:
        """Initialize the ElevenLabs streaming client.

        Args:
            api_key: The ElevenLabs API key.
            room_id: The meeting room identifier.
            user_id: The participant user identifier.
            on_transcript: Async callback function for transcript results.
                Called with parameters (text, is_final, confidence).
            language: ISO 639-1 language code.
            model: ElevenLabs model name. Defaults to ``"scribe_v2_realtime"``.
            sample_rate: Sample rate in Hz. Defaults to ``24000``.
        """
        self._api_key = api_key
        self.room_id = room_id
        self.user_id = user_id
        self.language = language
        self.model = model
        self.sample_rate = sample_rate
        self._on_transcript = on_transcript

        self._websocket: WebSocketClientProtocol | None = None
        self._listen_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._background_tasks: set[asyncio.Task] = set()

        self._connected = False
        self._intentional_close = False
        self._reconnect_attempts = 0
        self.last_activity = asyncio.get_event_loop().time()
        self._session_start_future: asyncio.Future[None] = asyncio.Future()

    async def connect(self) -> None:
        """Establish the WebSocket connection to ElevenLabs."""
        logger.info(
            "Connecting to ElevenLabs streaming STT for room=%s user=%s lang=%s",
            self.room_id,
            self.user_id,
            self.language,
        )

        lang_code = get_stt_language_code(self.language) or "en"

        # Build query parameters
        ws_url = (
            settings.ELEVENLABS_STT_WS_URL
            or "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
        )
        url = (
            f"{ws_url}?model_id={self.model}"
            f"&xi-api-key={self._api_key}"
            f"&language_code={lang_code}"
            f"&sample_rate={self.sample_rate}"
        )

        self._websocket = await websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=20,
        )

        self._connected = True
        self._intentional_close = False
        self._reconnect_attempts = 0
        self.last_activity = asyncio.get_event_loop().time()
        self._session_start_future = asyncio.Future()

        # Start listening loop as background task
        self._listen_task = asyncio.create_task(self._listen_loop())

        # Wait up to 5s for session_start message from ElevenLabs
        try:
            await asyncio.wait_for(self._session_start_future, timeout=5.0)
            logger.info(
                "ElevenLabs STT session started successfully for room=%s user=%s",
                self.room_id,
                self.user_id,
            )
        except TimeoutError:
            logger.warning(
                "Timeout waiting for ElevenLabs session_start "
                "message, proceeding anyway."
            )

    async def send_audio(self, audio_bytes: bytes) -> None:
        """Send raw audio bytes to the ElevenLabs WebSocket stream."""
        if not self._connected or not self._websocket:
            raise RuntimeError("ElevenLabs STT connection not established")

        self.last_activity = asyncio.get_event_loop().time()

        # ElevenLabs accepts base64-encoded audio chunk JSON messages
        base64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        message = {
            "message_type": "input_audio_chunk",
            "audio_base_64": base64_audio,
            "commit": False,
        }
        await self._websocket.send(json.dumps(message))

    async def close(self) -> None:
        """Gracefully close the ElevenLabs WebSocket stream connection."""
        self._intentional_close = True
        self._connected = False

        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None

        if self._websocket:
            try:
                # Send end of stream message
                end_message = {"message_type": "end_of_stream"}
                await self._websocket.send(json.dumps(end_message))
                # Wait briefly for server to finalize
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.warning(
                    "Error sending end_of_stream to ElevenLabs for room=%s user=%s: %s",
                    self.room_id,
                    self.user_id,
                    e,
                )

            try:
                await self._websocket.close()
            except Exception as e:
                logger.warning(
                    "Error closing ElevenLabs WebSocket for room=%s user=%s: %s",
                    self.room_id,
                    self.user_id,
                    e,
                )
            self._websocket = None

        if self._listen_task:
            self._listen_task.cancel()
            self._listen_task = None

        # Await any remaining callback tasks
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

        logger.info(
            "ElevenLabs streaming STT connection closed for room=%s user=%s",
            self.room_id,
            self.user_id,
        )

    async def _reconnect(self) -> None:
        """Attempt to reconnect with exponential backoff."""
        while self._reconnect_attempts < _MAX_RECONNECT_ATTEMPTS:
            self._reconnect_attempts += 1
            backoff = min(2**self._reconnect_attempts, 10)
            logger.warning(
                "ElevenLabs reconnect attempt %d/%d for room=%s "
                "user=%s (backoff=%.1fs)",
                self._reconnect_attempts,
                _MAX_RECONNECT_ATTEMPTS,
                self.room_id,
                self.user_id,
                backoff,
            )
            await asyncio.sleep(backoff)

            try:
                # Clean up old connection resources
                if self._websocket:
                    with contextlib.suppress(Exception):
                        await self._websocket.close()
                    self._websocket = None

                if self._listen_task:
                    self._listen_task.cancel()
                    self._listen_task = None

                # Reconnect
                await self.connect()
                logger.info(
                    "ElevenLabs reconnected successfully for room=%s user=%s",
                    self.room_id,
                    self.user_id,
                )
                return
            except Exception as e:
                logger.error(
                    "ElevenLabs reconnect attempt %d failed for room=%s user=%s: %s",
                    self._reconnect_attempts,
                    self.room_id,
                    self.user_id,
                    e,
                )

        logger.error(
            "ElevenLabs reconnection exhausted (%d attempts) for room=%s user=%s",
            _MAX_RECONNECT_ATTEMPTS,
            self.room_id,
            self.user_id,
        )

    async def _listen_loop(self) -> None:
        """Receive and process messages from ElevenLabs WebSocket."""
        try:
            while self._connected and self._websocket:
                message_str = await self._websocket.recv()
                self.last_activity = asyncio.get_event_loop().time()

                try:
                    message = json.loads(message_str)
                except json.JSONDecodeError:
                    logger.warning(
                        "Failed to decode JSON from ElevenLabs WebSocket: %s",
                        message_str,
                    )
                    continue

                self._process_message(message)

        except websockets.exceptions.ConnectionClosed as e:
            logger.info(
                "ElevenLabs STT WebSocket closed: code=%s, reason=%s", e.code, e.reason
            )
            self._handle_unexpected_disconnect()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(
                "Error in ElevenLabs STT listen loop for room=%s user=%s: %s",
                self.room_id,
                self.user_id,
                e,
            )
            self._handle_unexpected_disconnect()

    def _process_message(self, message: dict[str, Any]) -> None:
        """Process decoded message from ElevenLabs real-time STT WebSocket."""
        msg_type = message.get("message_type")

        if msg_type == "session_start":
            if not self._session_start_future.done():
                self._session_start_future.set_result(None)
            return

        if msg_type in ("partial_transcript", "committed_transcript"):
            is_final = msg_type == "committed_transcript"
            transcript = message.get("text", "").strip()

            # Estimate confidence or use 1.0/0.5
            confidence = 1.0 if is_final else 0.5

            if transcript:
                # Launch callback in background task
                task = asyncio.create_task(
                    self._on_transcript(transcript, is_final, confidence)
                )
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)

    def _handle_unexpected_disconnect(self) -> None:
        """Handle unexpected disconnect by scheduling a reconnection."""
        self._connected = False
        if not self._intentional_close:
            logger.warning(
                "Unexpected ElevenLabs disconnect for room=%s "
                "user=%s, scheduling reconnect",
                self.room_id,
                self.user_id,
            )
            self._reconnect_task = asyncio.create_task(self._reconnect())
