"""TTS (Text-to-Speech) Kafka consumer worker.

Consumes translated text from ``text.translated``, calls the configured
TTS provider (Deepgram, OpenAI, or Voice.ai), and publishes synthesized
audio to ``audio.synthesized``.

The active provider is controlled by ``settings.ACTIVE_TTS_PROVIDER``.
Automatic fallback to ``settings.TTS_FALLBACK_PROVIDER`` when the primary
provider fails (controlled by ``settings.TTS_FALLBACK_ENABLED``).
"""

import base64
import logging
import time
from typing import Any

from app.core.config import settings
from app.external_services.deepgram_tts.service import get_deepgram_tts_service
from app.external_services.elevenlabs_tts.service import get_elevenlabs_tts_service
from app.external_services.openai_tts.service import get_openai_tts_service
from app.external_services.voiceai.service import get_voiceai_tts_service
from app.external_services.voiceai.websocket_streaming import get_voiceai_ws_tts_service
from app.kafka.consumer import BaseConsumer
from app.kafka.schemas import BaseEvent
from app.kafka.topics import AUDIO_SYNTHESIZED, TEXT_TRANSLATED
from app.schemas.pipeline import (
    AudioEncoding,
    SynthesizedAudioEvent,
    SynthesizedAudioPayload,
    TranslationEvent,
)

logger = logging.getLogger(__name__)


class TTSWorker(BaseConsumer):
    """Kafka consumer that synthesizes translated text into audio.

    Subscribes to ``text.translated`` and publishes
    ``SynthesizedAudioEvent`` messages to ``audio.synthesized``.

    Supports two providers (switchable via ``ACTIVE_TTS_PROVIDER``):
        - ``"openai"`` — OpenAI TTS (tts-1)
        - ``"voiceai"`` — Voice.ai TTS (voiceai-tts-multilingual-v1-latest)

    Attributes:
        topic: The Kafka topic for incoming translated text events.
        group_id: Consumer group identifier for TTS generation.
        event_schema: Pydantic schema used to validate incoming translation events.
    """

    topic = TEXT_TRANSLATED
    group_id = "tts-worker-group"
    event_schema = TranslationEvent
    max_message_age_ms = 120_000  # skip translations from dead sessions

    async def handle(self, event: BaseEvent[Any]) -> None:
        """Process a translation: synthesize audio → publish.

        Tries the configured primary provider first.  If it fails and
        ``TTS_FALLBACK_ENABLED`` is ``True``, automatically retries with
        the fallback provider.

        Args:
            event (BaseEvent[Any]): The deserialized wrapper containing the
                TranslationPayload.
        """
        tl_event = TranslationEvent.model_validate(event.model_dump())
        payload = tl_event.payload

        pipeline_start = time.monotonic()

        text = payload.translated_text.strip()
        if not text:
            logger.warning(
                "Empty translated text for seq=%d, skipping TTS",
                payload.sequence_number,
            )
            return

        encoding = settings.PIPELINE_AUDIO_ENCODING
        provider = settings.ACTIVE_TTS_PROVIDER.lower()

        try:
            await self._dispatch_provider(
                provider, payload, text, encoding, pipeline_start
            )
        except Exception as primary_err:
            if not settings.TTS_FALLBACK_ENABLED:
                raise

            fallback = settings.TTS_FALLBACK_PROVIDER.lower()
            if fallback == provider:
                raise  # No point falling back to the same provider

            logger.warning(
                "Primary TTS provider '%s' failed for seq=%d: %s. "
                "Falling back to '%s'.",
                provider,
                payload.sequence_number,
                primary_err,
                fallback,
            )
            # Fallback attempt — if this also fails, the exception
            # propagates to BaseConsumer._process_with_retry as normal.
            await self._dispatch_provider(
                fallback, payload, text, encoding, pipeline_start
            )

    async def _dispatch_provider(
        self,
        provider: str,
        payload: Any,
        text: str,
        encoding: str,
        pipeline_start: float,
    ) -> None:
        """Route synthesis to the specified provider."""
        if provider == "elevenlabs" and settings.ELEVENLABS_TTS_USE_STREAMING:
            await self._handle_elevenlabs_streaming(
                payload, text, encoding, pipeline_start
            )
            return

        use_ws = provider == "voiceai" and settings.VOICEAI_USE_WEBSOCKET
        use_streaming = (
            provider == "voiceai" and settings.VOICEAI_USE_STREAMING and not use_ws
        )

        if use_ws:
            await self._handle_ws_streaming(payload, text, encoding, pipeline_start)
            return

        if use_streaming:
            await self._handle_http_streaming(payload, text, encoding, pipeline_start)
            return

        await self._handle_batch_synthesis(
            payload, text, encoding, pipeline_start, provider=provider
        )

    async def _handle_ws_streaming(
        self,
        payload: Any,
        text: str,
        encoding: str,
        pipeline_start: float,
    ) -> None:
        """Handle Voice.ai WebSocket multi-context streaming path."""
        context_id = (
            f"{payload.room_id}:{payload.target_language}:{payload.sequence_number}"
        )
        accumulated_bytes = bytearray()
        sample_rate = 24000

        async for chunk_data in get_voiceai_ws_tts_service().synthesize_stream(
            text=text,
            context_id=context_id,
            language=payload.target_language,
            encoding=encoding,
        ):
            chunk_bytes = chunk_data["audio_bytes"]
            sample_rate = chunk_data["sample_rate"]
            accumulated_bytes.extend(chunk_bytes)

            chunk_b64 = base64.b64encode(chunk_bytes).decode("ascii")
            synth_payload = SynthesizedAudioPayload(
                room_id=payload.room_id,
                user_id=payload.user_id,
                sequence_number=payload.sequence_number,
                audio_data=chunk_b64,
                target_language=payload.target_language,
                sample_rate=sample_rate,
                encoding=AudioEncoding(encoding),
            )
            synth_event = SynthesizedAudioEvent(payload=synth_payload)
            try:
                await self._publish_audio_to_redis(synth_event)
            except Exception as redis_err:
                logger.warning("Redis audio egress publish failed: %s", redis_err)

        if accumulated_bytes:
            full_audio_b64 = base64.b64encode(accumulated_bytes).decode("ascii")
            final_payload = SynthesizedAudioPayload(
                room_id=payload.room_id,
                user_id=payload.user_id,
                sequence_number=payload.sequence_number,
                audio_data=full_audio_b64,
                target_language=payload.target_language,
                sample_rate=sample_rate,
                encoding=AudioEncoding(encoding),
            )
            final_event = SynthesizedAudioEvent(payload=final_payload)
            await self._producer.send(
                AUDIO_SYNTHESIZED, final_event, key=payload.room_id
            )

            elapsed_ms = (time.monotonic() - pipeline_start) * 1000
            logger.info(
                "TTS (WS Final): seq=%d room=%s lang=%s "
                "provider=%s audio_size=%d latency=%.1fms",
                payload.sequence_number,
                payload.room_id,
                payload.target_language,
                settings.ACTIVE_TTS_PROVIDER,
                len(accumulated_bytes),
                elapsed_ms,
            )

    async def _handle_http_streaming(
        self,
        payload: Any,
        text: str,
        encoding: str,
        pipeline_start: float,
    ) -> None:
        """Handle Voice.ai HTTP streaming path."""
        accumulated_bytes = bytearray()
        sample_rate = 24000

        async for chunk_data in get_voiceai_tts_service().synthesize_stream(
            text=text,
            language=payload.target_language,
            encoding=encoding,
        ):
            chunk_bytes = chunk_data["audio_bytes"]
            sample_rate = chunk_data["sample_rate"]
            accumulated_bytes.extend(chunk_bytes)

            chunk_b64 = base64.b64encode(chunk_bytes).decode("ascii")
            synth_payload = SynthesizedAudioPayload(
                room_id=payload.room_id,
                user_id=payload.user_id,
                sequence_number=payload.sequence_number,
                audio_data=chunk_b64,
                target_language=payload.target_language,
                sample_rate=sample_rate,
                encoding=AudioEncoding(encoding),
            )
            synth_event = SynthesizedAudioEvent(payload=synth_payload)
            try:
                await self._publish_audio_to_redis(synth_event)
            except Exception as redis_err:
                logger.warning("Redis audio egress publish failed: %s", redis_err)

        if accumulated_bytes:
            full_audio_b64 = base64.b64encode(accumulated_bytes).decode("ascii")
            final_payload = SynthesizedAudioPayload(
                room_id=payload.room_id,
                user_id=payload.user_id,
                sequence_number=payload.sequence_number,
                audio_data=full_audio_b64,
                target_language=payload.target_language,
                sample_rate=sample_rate,
                encoding=AudioEncoding(encoding),
            )
            final_event = SynthesizedAudioEvent(payload=final_payload)
            await self._producer.send(
                AUDIO_SYNTHESIZED, final_event, key=payload.room_id
            )

            elapsed_ms = (time.monotonic() - pipeline_start) * 1000
            logger.info(
                "TTS (Stream Final): seq=%d room=%s lang=%s "
                "provider=%s audio_size=%d latency=%.1fms",
                payload.sequence_number,
                payload.room_id,
                payload.target_language,
                settings.ACTIVE_TTS_PROVIDER,
                len(accumulated_bytes),
                elapsed_ms,
            )

    async def _handle_elevenlabs_streaming(
        self,
        payload: Any,
        text: str,
        encoding: str,
        pipeline_start: float,
    ) -> None:
        """Handle ElevenLabs HTTP streaming path."""
        accumulated_bytes = bytearray()
        sample_rate = 24000

        async for chunk_data in get_elevenlabs_tts_service().synthesize_stream(
            text=text,
            language=payload.target_language,
            encoding=encoding,
        ):
            chunk_bytes = chunk_data["audio_bytes"]
            sample_rate = chunk_data["sample_rate"]
            accumulated_bytes.extend(chunk_bytes)

            chunk_b64 = base64.b64encode(chunk_bytes).decode("ascii")
            synth_payload = SynthesizedAudioPayload(
                room_id=payload.room_id,
                user_id=payload.user_id,
                sequence_number=payload.sequence_number,
                audio_data=chunk_b64,
                target_language=payload.target_language,
                sample_rate=sample_rate,
                encoding=AudioEncoding(encoding),
            )
            synth_event = SynthesizedAudioEvent(payload=synth_payload)
            try:
                await self._publish_audio_to_redis(synth_event)
            except Exception as redis_err:
                logger.warning("Redis audio egress publish failed: %s", redis_err)

        if accumulated_bytes:
            full_audio_b64 = base64.b64encode(accumulated_bytes).decode("ascii")
            final_payload = SynthesizedAudioPayload(
                room_id=payload.room_id,
                user_id=payload.user_id,
                sequence_number=payload.sequence_number,
                audio_data=full_audio_b64,
                target_language=payload.target_language,
                sample_rate=sample_rate,
                encoding=AudioEncoding(encoding),
            )
            final_event = SynthesizedAudioEvent(payload=final_payload)
            await self._producer.send(
                AUDIO_SYNTHESIZED, final_event, key=payload.room_id
            )

            elapsed_ms = (time.monotonic() - pipeline_start) * 1000
            logger.info(
                "TTS (ElevenLabs Stream Final): seq=%d room=%s lang=%s "
                "provider=elevenlabs audio_size=%d latency=%.1fms",
                payload.sequence_number,
                payload.room_id,
                payload.target_language,
                len(accumulated_bytes),
                elapsed_ms,
            )

    async def _handle_batch_synthesis(
        self,
        payload: Any,
        text: str,
        encoding: str,
        pipeline_start: float,
        *,
        provider: str | None = None,
    ) -> None:
        """Handle standard non-streaming batch synthesis path."""
        provider = provider or settings.ACTIVE_TTS_PROVIDER.lower()

        # 1. Call the configured TTS provider (Non-streaming)
        audio_result = await self._synthesize(
            text=text,
            language=payload.target_language,
            encoding=encoding,
            provider=provider,
        )

        audio_bytes = audio_result["audio_bytes"]
        sample_rate = audio_result["sample_rate"]

        # 2. Base64 encode for Kafka transport
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")

        # 3. Build and publish synthesized audio event
        synth_payload = SynthesizedAudioPayload(
            room_id=payload.room_id,
            user_id=payload.user_id,
            sequence_number=payload.sequence_number,
            audio_data=audio_b64,
            target_language=payload.target_language,
            sample_rate=sample_rate,
            encoding=AudioEncoding(encoding),
        )
        synth_event = SynthesizedAudioEvent(payload=synth_payload)

        await self._producer.send(AUDIO_SYNTHESIZED, synth_event, key=payload.room_id)

        # Publish to Redis Pub/Sub for real-time WebSocket egress delivery
        try:
            await self._publish_audio_to_redis(synth_event)
        except Exception as redis_err:
            logger.warning("Redis audio egress publish failed: %s", redis_err)

        # 4. Log pipeline latency
        elapsed_ms = (time.monotonic() - pipeline_start) * 1000
        logger.info(
            "TTS: seq=%d room=%s lang=%s provider=%s audio_size=%d latency=%.1fms",
            payload.sequence_number,
            payload.room_id,
            payload.target_language,
            provider,
            len(audio_bytes),
            elapsed_ms,
        )

    async def _synthesize(
        self,
        *,
        text: str,
        language: str,
        encoding: str,
        provider: str | None = None,
    ) -> dict:
        """Dispatch to the specified TTS provider.

        Args:
            text (str): The translated native text to synthesize.
            language (str): The language code of the text.
            encoding (str): The desired output audio format encoding.
            provider (str | None): Provider name override. Falls back to
                ``settings.ACTIVE_TTS_PROVIDER``.

        Returns:
            dict: A dictionary containing 'audio_bytes' and the 'sample_rate'
                metadata.
        """
        provider = (provider or settings.ACTIVE_TTS_PROVIDER).lower()

        if provider == "elevenlabs":
            return await get_elevenlabs_tts_service().synthesize(
                text, language=language, encoding=encoding
            )

        if provider == "deepgram":
            return await get_deepgram_tts_service().synthesize(
                text, language=language, encoding=encoding
            )

        if provider == "voiceai":
            return await get_voiceai_tts_service().synthesize(
                text, language=language, encoding=encoding
            )

        # Default: OpenAI
        return await get_openai_tts_service().synthesize(
            text, language=language, encoding=encoding
        )

    async def _publish_audio_to_redis(self, synth_event: SynthesizedAudioEvent) -> None:
        """Publish synthesized audio to Redis Pub/Sub for WebSocket egress."""
        import json

        from app.modules.auth.token_store import _get_redis_client

        redis = _get_redis_client()
        await redis.publish(
            f"pipeline:audio:{synth_event.payload.room_id}",
            json.dumps(synth_event.model_dump(), default=str),
        )
