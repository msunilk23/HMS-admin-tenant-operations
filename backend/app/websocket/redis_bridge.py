"""
Redis pub/sub bridge.

Subscribes to all tenant event channels and forwards messages
to connected WebSocket clients via the WebSocketManager.

Channel naming convention:
  {tenant_schema}:{event_type}
  e.g.  shankar:queue:update
        shankar:visit:update
        shankar:pharmacy:update
"""

import asyncio
import json
import logging

import redis.asyncio as aioredis

from app.core.config import settings
from app.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)
_subscriber_task: asyncio.Task | None = None


async def start_redis_subscriber(manager: WebSocketManager) -> asyncio.Task:
    """
    Called at app startup. Runs the subscriber loop as a background task
    so it doesn't block the server.
    """
    global _subscriber_task
    _subscriber_task = asyncio.create_task(_subscriber_loop(manager))
    return _subscriber_task


async def stop_redis_subscriber() -> None:
    global _subscriber_task
    if _subscriber_task:
        _subscriber_task.cancel()
        try:
            await _subscriber_task
        except asyncio.CancelledError:
            pass
        _subscriber_task = None


async def _subscriber_loop(manager: WebSocketManager) -> None:
    while True:
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = client.pubsub()
        try:
            await pubsub.psubscribe("*:*")
            async for raw_message in pubsub.listen():
                if raw_message["type"] != "pmessage":
                    continue
                channel: str = raw_message["channel"]
                try:
                    parts = channel.split(":", 1)
                    if len(parts) != 2:
                        continue
                    tenant, event_channel = parts
                    data = json.loads(raw_message["data"])
                    await manager.broadcast_local(tenant, event_channel, data)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    logger.warning("Ignoring malformed or unauthorized Redis event: %s", channel)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Redis subscriber disconnected; retrying")
            await asyncio.sleep(1)
        finally:
            try:
                await pubsub.close()
                await client.aclose()
            except Exception:
                pass


async def publish_event(tenant: str, channel: str, message: dict) -> None:
    """
    Helper used by services to publish a real-time event.
    e.g. await publish_event("shankar", "queue:update", {"token_no": 42, "status": "called"})
    """
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    await client.publish(f"{tenant}:{channel}", json.dumps(message))
    await client.aclose()
