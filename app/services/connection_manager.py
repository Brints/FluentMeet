"""WebSocket Connection Manager with Redis Pub/Sub backplane.

Manages active WebSocket connections per room and user.
Uses Redis Pub/Sub to allow broadcasting messages across multiple
application instances.

For example, if User A (connected to Pod 1) sends a signaling message
to Room X, it's published to the Redis channel for Room X. Pod 2 receives
it and sends it to User B's WebSocket.
"""

import asyncio
import json
import logging

from fastapi import WebSocket
from redis.asyncio import Redis

from app.core.sanitize import log_sanitizer

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections and multi-instance Pub/Sub scaling."""

    def __init__(self, redis_client: Redis) -> None:
        # Maps room_code -> { user_id -> WebSocket }
        self.active_connections: dict[str, dict[str, WebSocket]] = {}
        # Maps room_code -> BackgroundTask (Redis subscriber)
        self._pubsub_tasks: dict[str, asyncio.Task] = {}
        self.redis = redis_client

    async def connect(self, room_code: str, user_id: str, websocket: WebSocket) -> None:
        """Register an accepted WebSocket connection in the manager."""
        if room_code not in self.active_connections:
            self.active_connections[room_code] = {}
            # Start pub/sub listener for the room
            self._start_listening(room_code)

        self.active_connections[room_code][user_id] = websocket
        logger.info(
            "User %s connected to room %s",
            log_sanitizer.sanitize(user_id),
            log_sanitizer.sanitize(room_code),
        )

    def disconnect(self, room_code: str, user_id: str) -> None:
        """Remove a WebSocket connection from the manager."""
        if room_code in self.active_connections:
            self.active_connections[room_code].pop(user_id, None)
            logger.info(
                "User %s disconnected from room %s",
                log_sanitizer.sanitize(user_id),
                log_sanitizer.sanitize(room_code),
            )

            # Clean up empty rooms
            if not self.active_connections[room_code]:
                del self.active_connections[room_code]
                self._stop_listening(room_code)

    async def broadcast_to_room(
        self, room_code: str, message: dict, sender_id: str | None = None
    ) -> None:
        """Publish a message to all users in a room across all instances."""
        payload = {"type": "broadcast", "sender_id": sender_id, "data": message}
        await self.redis.publish(self._get_channel_name(room_code), json.dumps(payload))

    async def send_to_user(
        self, room_code: str, target_user_id: str, message: dict
    ) -> None:
        """Publish a message to a specific user in a room across all instances."""
        payload = {"type": "unicast", "target_user_id": target_user_id, "data": message}
        await self.redis.publish(self._get_channel_name(room_code), json.dumps(payload))

    # ── Internal Redis Pub/Sub Logic ─────────────────────────────────

    def _get_channel_name(self, room_code: str) -> str:
        return f"ws:room:{room_code}"

    def _start_listening(self, room_code: str) -> None:
        """Start a background task to listen for room messages on Redis."""
        if room_code not in self._pubsub_tasks:
            task = asyncio.create_task(self._listen_to_redis(room_code))
            self._pubsub_tasks[room_code] = task

    def _stop_listening(self, room_code: str) -> None:
        """Cancel the background task listening for room messages."""
        task = self._pubsub_tasks.pop(room_code, None)
        if task and not task.done():
            task.cancel()

    async def _listen_to_redis(self, room_code: str) -> None:  # noqa: C901
        """Listen to a Redis channel and dispatch to local websockets."""
        pubsub = self.redis.pubsub()
        channel = self._get_channel_name(room_code)
        await pubsub.subscribe(channel)

        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                payload = json.loads(message["data"])
                msg_type = payload.get("type")
                data = payload.get("data")

                # Check if room is still active locally
                if room_code not in self.active_connections:
                    break

                if msg_type == "broadcast":
                    sender_id = payload.get("sender_id")
                    for user_id, ws in list(self.active_connections[room_code].items()):
                        # Don't echo back to the sender
                        if user_id != sender_id:
                            try:
                                await ws.send_json(data)
                            except Exception:
                                logger.warning(
                                    "Failed to send message to %s",
                                    log_sanitizer.sanitize(user_id),
                                )

                elif msg_type == "unicast":
                    target_id = payload.get("target_user_id")
                    target_ws = self.active_connections[room_code].get(target_id)
                    if target_ws:
                        try:
                            await target_ws.send_json(data)
                        except Exception:
                            logger.warning(
                                "Failed to send unicast message to %s",
                                log_sanitizer.sanitize(target_id),
                            )
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)


# ── Module-level Dependency ───────────────────────────────────────────

from app.modules.auth.token_store import _get_redis_client  # noqa: E402

# We keep a singleton reference for the application lifecycle
_connection_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    global _connection_manager  # noqa: PLW0603
    if _connection_manager is None:
        # Create it synchronously but pass the global Redis client
        redis_client = _get_redis_client()
        _connection_manager = ConnectionManager(redis_client)
    return _connection_manager
