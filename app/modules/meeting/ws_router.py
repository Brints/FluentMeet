"""Meeting WebSockets Integrations module.

WebSocket endpoints for real-time signaling, audio streaming, and captions.
"""

import asyncio
import base64
import json
import logging
import time

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.core.sanitize import log_sanitizer, sanitize_for_log
from app.modules.meeting.state import MeetingStateService
from app.modules.meeting.ws_dependencies import (
    assert_lobby_participant,
    assert_room_participant,
    authenticate_ws,
)
from app.schemas.pipeline import (
    SynthesizedAudioEvent,
)
from app.services.audio_bridge import get_audio_ingest_service
from app.services.connection_manager import get_connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websockets"])


@router.websocket("/signaling/{room_code}")
async def signaling_websocket(
    websocket: WebSocket,
    room_code: str,
    user_id: str = Depends(authenticate_ws),
) -> None:
    """Relays WebRTC Offer, Answer, and ICE Candidate messages between peers.

    Args:
        websocket (WebSocket): Protocol mapping.
        room_code (str): Video URL param.
        user_id (str): Extracted authenticated bounds.
    """
    try:
        participant_state = await assert_room_participant(room_code, user_id)
    except Exception as e:
        await websocket.close(code=1008, reason=str(e))
        return

    await websocket.accept()

    manager = get_connection_manager()
    await manager.connect(room_code, user_id, websocket)

    # Announce this peer to everyone already in the room so the participant
    # panel updates immediately without waiting for WebRTC negotiation.
    display_name = participant_state.get("display_name", "")
    role = participant_state.get("role", "guest")
    await manager.broadcast_to_room(
        room_code,
        {
            "type": "user_joined",
            "user_id": user_id,
            "display_name": display_name,
            "role": role,
        },
        sender_id=user_id,  # Don't echo back to the joiner themselves
    )

    # Tell the new user about all existing users so they can update their UI immediately
    participants = await MeetingStateService().get_participants(room_code)
    existing_users = [
        {
            "user_id": pid,
            "display_name": pstate.get("display_name", ""),
            "role": pstate.get("role", "guest"),
        }
        for pid, pstate in participants.items()
        if pid != user_id
    ]
    await websocket.send_json({"type": "existing_users", "users": existing_users})

    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                target_user_id = payload.get("target_user_id")

                # Always inject the sender's identity so the recipient knows
                # who sent the offer/answer/ice_candidate.
                payload["from_user_id"] = user_id

                # If target specified, unicast. Otherwise, broadcast.
                if target_user_id:
                    await manager.send_to_user(room_code, target_user_id, payload)
                else:
                    await manager.broadcast_to_room(
                        room_code, payload, sender_id=user_id
                    )
            except json.JSONDecodeError:
                logger.warning("Invalid JSON received on signaling WS")

    except WebSocketDisconnect:
        manager.disconnect(room_code, user_id)
        # Notify others that this peer left (use user_left to match frontend model)
        await manager.broadcast_to_room(
            room_code, {"type": "user_left", "user_id": user_id}, sender_id=user_id
        )


@router.websocket("/audio/{room_code}")
async def audio_websocket(  # noqa: C901
    websocket: WebSocket,
    room_code: str,
    user_id: str = Depends(authenticate_ws),
) -> None:
    """Bidirectional audio stream.

    Args:
        websocket (WebSocket): Protocol native tracker.
        room_code (str): Room id.
        user_id (str): Authenticated limit string.
    """
    try:
        participant_state = await assert_room_participant(room_code, user_id)
    except Exception as e:
        await websocket.close(code=1008, reason=str(e))
        return

    listening_language = participant_state.get("language", "en")
    await websocket.accept()
    logger.info("Audio WS client connected: %s", sanitize_for_log(user_id))

    ingest_svc = get_audio_ingest_service()
    ingest_svc.reset_sequence(f"{room_code}:{user_id}")

    async def ingest_task() -> None:
        """Reads WS binary frames (or Base64 text), packages, and sends to Kafka."""
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    logger.info(
                        "Audio WS ingest got disconnect frame for %s",
                        log_sanitizer.sanitize(user_id),
                    )
                    break
                if message.get("text"):
                    try:
                        data = base64.b64decode(message["text"])
                    except Exception as exc:
                        logger.warning(
                            f"Failed to decode base64 audio text frame. "
                            f"Skipping frame. Error: {exc}"
                        )
                        continue
                elif "bytes" in message and message["bytes"] is not None:
                    data = message["bytes"]
                else:
                    # Ignore close frames or other control messages here
                    continue

                # Chunk the data to avoid Kafka MessageSizeTooLargeError
                # and to simulate standard continuous client streaming
                chunk_size = 500 * 1024  # 500 KB per chunk safely under 1MB limit

                for i in range(0, len(data), chunk_size):
                    chunk = data[i : i + chunk_size]
                    await ingest_svc.publish_audio_chunk(
                        room_id=room_code,
                        user_id=user_id,
                        audio_bytes=chunk,
                        # Use speaking_language — not
                        # listening_language so STT
                        # transcribes in the correct language.
                        source_language=participant_state.get(
                            "speaking_language", "en"
                        ),
                    )
        except WebSocketDisconnect:
            logger.info(
                "Audio WS client disconnected (WebSocketDisconnect): %s",
                sanitize_for_log(user_id),
            )
        except RuntimeError as exc:
            # Starlette raises RuntimeError once the disconnect frame has been
            # consumed. Treat it the same as a clean disconnect.
            if (
                "disconnect" not in str(exc).lower()
                and "websocket" not in str(exc).lower()
            ):
                raise
            logger.info(
                "Audio WS ingest RuntimeError (socket already closed) for %s: %s",
                sanitize_for_log(user_id),
                exc,
            )

    # --- Shared event so egress consumer is ready before we start ingesting ---
    egress_ready = asyncio.Event()

    async def egress_task() -> None:
        """Reads Redis Pub/Sub synthesized audio, filters for user, writes to WS."""
        from app.modules.auth.token_store import _get_redis_client

        redis = _get_redis_client()
        pubsub = redis.pubsub()
        channel = f"pipeline:audio:{room_code}"
        await pubsub.subscribe(channel)

        egress_ready.set()  # Signal that we are ready to receive

        # Track the highest sequence seen to drop stale frames
        highest_seq: dict[str, int] = {}
        # Cache participant count to avoid per-frame Redis lookups
        _cached_participant_count: int = 0
        _cache_ts: float = 0.0

        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                try:
                    event = SynthesizedAudioEvent.model_validate(
                        json.loads(message["data"])
                    )
                    payload = event.payload

                    # Room filter is implicit (we subscribed to room-specific channel)

                    # Language filter with cached participant count
                    now = time.time()
                    if now - _cache_ts > 5.0:
                        participants = await MeetingStateService().get_participants(
                            room_code
                        )
                        _cached_participant_count = len(participants)
                        _cache_ts = now

                    if (
                        _cached_participant_count > 1
                        and payload.target_language != listening_language
                    ):
                        continue

                    # Stale frame guard (drop if more than 10 sequences behind)
                    speaker_key = payload.user_id
                    current_highest = highest_seq.get(speaker_key, -1)

                    if payload.sequence_number < current_highest - 10:
                        continue

                    highest_seq[speaker_key] = max(
                        current_highest, payload.sequence_number
                    )

                    # Send synthesized audio to the listener's WebSocket
                    audio_bytes = base64.b64decode(payload.audio_data)
                    try:
                        await websocket.send_bytes(audio_bytes)
                    except Exception as send_err:
                        logger.warning(
                            "Egress: WebSocket send failed for user=%s: %s",
                            sanitize_for_log(user_id),
                            send_err,
                        )
                        break

                except Exception as frame_err:
                    logger.exception("Error processing egress frame: %s", frame_err)

        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)

    async def guarded_ingest_task() -> None:
        """Wait for egress consumer to be ready, then start ingesting."""
        await egress_ready.wait()
        logger.info("Egress ready — starting audio ingest")
        await ingest_task()

    task1 = asyncio.create_task(guarded_ingest_task())
    task2 = asyncio.create_task(egress_task())

    try:
        # Run until either task fails or disconnects
        _done, pending = await asyncio.wait(
            [task1, task2], return_when=asyncio.FIRST_COMPLETED
        )
        # Cancel whatever is still running
        for t in pending:
            t.cancel()
    except Exception:
        pass


@router.websocket("/captions/{room_code}")
async def captions_websocket(
    websocket: WebSocket,
    room_code: str,
    user_id: str = Depends(authenticate_ws),
) -> None:
    """Broadcasts original and translated transcription events via Redis Pub/Sub."""
    try:
        _ = await assert_room_participant(room_code, user_id)
    except Exception as e:
        await websocket.close(code=1008, reason=str(e))
        return

    await websocket.accept()

    from app.modules.auth.token_store import _get_redis_client

    redis = _get_redis_client()
    pubsub = redis.pubsub()
    channel = f"pipeline:captions:{room_code}"
    await pubsub.subscribe(channel)

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                caption_data = json.loads(message["data"])
                # Only forward captions for this room (implicit via channel)
                await websocket.send_json(caption_data)
            except Exception as frame_err:
                logger.warning("Error processing caption frame: %s", frame_err)

    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe(channel)


@router.websocket("/lobby/{room_code}")
async def lobby_websocket(
    websocket: WebSocket,
    room_code: str,
    user_id: str = Depends(authenticate_ws),
) -> None:
    """WebSocket for users waiting in the lobby.

    Lobby users connect here after POST /join returns {"status": "waiting"}.
    They receive real-time server-pushed events:
    - {"type": "admitted"} -> user should close this WS and connect to signaling
    - {"type": "rejected"} -> user should close this WS and show rejection UI
    - {"type": "meeting_ended"} -> meeting was ended while user was waiting

    They can also SEND client messages:
    - {"type": "cancel"} -> user cancels their wait (removes from lobby)
    """
    try:
        _ = await assert_lobby_participant(room_code, user_id)
    except Exception as e:
        await websocket.close(code=1008, reason=str(e))
        return

    await websocket.accept()

    manager = get_connection_manager()
    await manager.connect_lobby(room_code, user_id, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                msg_type = payload.get("type")
                if msg_type == "cancel":
                    from app.modules.meeting.service import MeetingService
                    from app.modules.meeting.state import MeetingStateService

                    state = MeetingStateService()
                    service = MeetingService(repo=None, state=state)  # type: ignore[arg-type]
                    await service.cancel_lobby_wait(room_code, user_id)
                    await websocket.close(code=1000, reason="Canceled wait")
                    break
            except json.JSONDecodeError:
                logger.warning("Invalid JSON received on lobby WS")
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect_lobby(room_code, user_id)
