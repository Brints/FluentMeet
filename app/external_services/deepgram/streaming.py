"""Deepgram Speech-to-Text WebSocket streaming client.

Wraps the Deepgram SDK's AsyncV1SocketClient to support continuous real-time audio
streaming and handle interim & final transcription events.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from deepgram.listen.v1.socket_client import AsyncV1SocketClient
from deepgram.listen.v1.types import ListenV1Results

from app.core.config import settings

logger = logging.getLogger(__name__)

# Maximum number of automatic reconnection attempts before giving up.
_MAX_RECONNECT_ATTEMPTS = 3


class DeepgramStreamingSTT:
    """Wrapper around Deepgram's SDK Async WebSocket connection for live STT."""

    def __init__(
        self,
        api_key: str,
        room_id: str,
        user_id: str,
        on_transcript: Callable[[str, bool, float], Coroutine[Any, Any, None]],
        language: str = "en",
        model: str = "nova-2",
        sample_rate: int = 16000,
    ) -> None:
        """Initialize the Deepgram streaming client.

        Args:
            api_key: The Deepgram API key.
            room_id: The meeting room identifier.
            user_id: The participant user identifier.
            on_transcript: Async callback function for transcript results.
                Called with parameters (text, is_final, confidence).
            language: ISO 639-1 language code.
            model: Deepgram model name.
            sample_rate: Sample rate in Hz.
        """
        self._api_key = api_key
        self.room_id = room_id
        self.user_id = user_id
        self.language = language
        self.model = model
        self.sample_rate = sample_rate
        self._on_transcript = on_transcript

        self._client = AsyncDeepgramClient(api_key=self._api_key)
        self._connection: AsyncV1SocketClient | None = None
        self._ctx: Any = None
        self._listen_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._background_tasks: set[asyncio.Task] = set()
        self._connected = False
        self._intentional_close = False
        self._reconnect_attempts = 0
        self.last_activity = asyncio.get_event_loop().time()

    async def connect(self) -> None:
        """Establish the WebSocket connection to Deepgram."""
        logger.info(
            "Connecting to Deepgram streaming STT for room=%s user=%s lang=%s",
            self.room_id,
            self.user_id,
            self.language,
        )

        self._ctx = self._client.listen.v1.connect(
            model=self.model,
            language=self.language,
            encoding="linear16",
            sample_rate=str(self.sample_rate),
            punctuate="true",
            smart_format="true",
            interim_results=str(settings.DEEPGRAM_INTERIM_RESULTS).lower(),
            endpointing=str(settings.DEEPGRAM_ENDPOINTING_MS),
        )
        self._connection = await self._ctx.__aenter__()

        self._connected = True
        self._intentional_close = False
        self._reconnect_attempts = 0
        self.last_activity = asyncio.get_event_loop().time()

        # Register event handlers
        self._connection.on(EventType.MESSAGE, self._handle_message)
        self._connection.on(EventType.ERROR, self._handle_error)
        self._connection.on(EventType.CLOSE, self._handle_close)

        # Start listening in a background task
        self._listen_task = asyncio.create_task(self._connection.start_listening())

        # Start keepalive task
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def send_audio(self, audio_bytes: bytes) -> None:
        """Send raw audio bytes to the Deepgram WebSocket stream."""
        if not self._connected or not self._connection:
            raise RuntimeError("Deepgram STT connection not established")

        self.last_activity = asyncio.get_event_loop().time()
        await self._connection.send_media(audio_bytes)

    async def close(self) -> None:
        """Gracefully close the Deepgram WebSocket stream connection."""
        self._intentional_close = True
        self._connected = False

        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None

        if self._keepalive_task:
            self._keepalive_task.cancel()
            self._keepalive_task = None

        if self._connection:
            try:
                await self._connection.send_close_stream()
            except Exception as e:
                logger.warning(
                    "Error sending close stream for room=%s user=%s: %s",
                    self.room_id,
                    self.user_id,
                    e,
                )

        if self._ctx:
            try:
                await self._ctx.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(
                    "Error exiting connection context for room=%s user=%s: %s",
                    self.room_id,
                    self.user_id,
                    e,
                )
            self._ctx = None
            self._connection = None

        if self._listen_task:
            self._listen_task.cancel()
            self._listen_task = None

        logger.info(
            "Deepgram streaming STT connection closed for room=%s user=%s",
            self.room_id,
            self.user_id,
        )

    async def _reconnect(self) -> None:
        """Attempt to reconnect with exponential backoff."""
        while self._reconnect_attempts < _MAX_RECONNECT_ATTEMPTS:
            self._reconnect_attempts += 1
            backoff = min(2**self._reconnect_attempts, 10)
            logger.warning(
                "Deepgram reconnect attempt %d/%d for room=%s user=%s (backoff=%.1fs)",
                self._reconnect_attempts,
                _MAX_RECONNECT_ATTEMPTS,
                self.room_id,
                self.user_id,
                backoff,
            )
            await asyncio.sleep(backoff)

            try:
                # Clean up old connection resources
                if self._ctx:
                    with contextlib.suppress(Exception):
                        await self._ctx.__aexit__(None, None, None)
                    self._ctx = None
                    self._connection = None

                if self._listen_task:
                    self._listen_task.cancel()
                    self._listen_task = None

                if self._keepalive_task:
                    self._keepalive_task.cancel()
                    self._keepalive_task = None

                # Re-create client and connect
                self._client = AsyncDeepgramClient(api_key=self._api_key)
                await self.connect()
                logger.info(
                    "Deepgram reconnected successfully for room=%s user=%s",
                    self.room_id,
                    self.user_id,
                )
                return
            except Exception as e:
                logger.error(
                    "Deepgram reconnect attempt %d failed for room=%s user=%s: %s",
                    self._reconnect_attempts,
                    self.room_id,
                    self.user_id,
                    e,
                )

        logger.error(
            "Deepgram reconnection exhausted (%d attempts) for room=%s user=%s",
            _MAX_RECONNECT_ATTEMPTS,
            self.room_id,
            self.user_id,
        )

    async def _keepalive_loop(self) -> None:
        """Periodically send keepalive messages to prevent timeouts."""
        try:
            while self._connected and self._connection:
                await asyncio.sleep(5.0)
                await self._connection.send_keep_alive()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(
                "Deepgram keepalive error for room=%s user=%s: %s",
                self.room_id,
                self.user_id,
                e,
            )

    def _handle_message(self, message: Any) -> None:
        """Handle transcription messages from Deepgram."""
        self.last_activity = asyncio.get_event_loop().time()
        if not isinstance(message, ListenV1Results):
            return

        is_final = message.is_final if message.is_final is not None else True

        try:
            channel = message.channel
            if not channel:
                return
            alternatives = channel.alternatives
            if not alternatives:
                return
            alternative = alternatives[0]
            transcript = alternative.transcript.strip()
            confidence = alternative.confidence

            if transcript:
                # Call transcript callback in a background task
                task = asyncio.create_task(
                    self._on_transcript(transcript, is_final, confidence)
                )
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
        except Exception as e:
            logger.error(
                "Error processing Deepgram message for room=%s user=%s: %s",
                self.room_id,
                self.user_id,
                e,
            )

    def _handle_error(self, error: Exception) -> None:
        """Handle connection errors."""
        logger.error(
            "Deepgram streaming STT error for room=%s user=%s: %s",
            self.room_id,
            self.user_id,
            error,
        )

    def _handle_close(self, _data: Any) -> None:
        """Handle connection close event. Triggers auto-reconnect if unexpected."""
        logger.info(
            "Deepgram streaming STT connection closed callback for room=%s user=%s",
            self.room_id,
            self.user_id,
        )
        self._connected = False

        # Auto-reconnect on unexpected disconnects
        if not self._intentional_close:
            logger.warning(
                "Unexpected Deepgram disconnect for room=%s user=%s, "
                "scheduling reconnect",
                self.room_id,
                self.user_id,
            )
            self._reconnect_task = asyncio.create_task(self._reconnect())
