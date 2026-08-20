import asyncio

import pytest

from app.websocket.manager import ALLOWED_EVENT_CHANNELS, WebSocketManager


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def accept(self):
        pass

    async def send_text(self, payload):
        self.messages.append(payload)


@pytest.mark.asyncio
async def test_broadcast_publishes_without_local_duplicate(monkeypatch):
    manager = WebSocketManager()
    socket = FakeWebSocket()
    await manager.connect(socket, "tenant_a", "queue:update")
    published = []

    async def fake_publish(tenant, channel, message):
        published.append((tenant, channel, message))

    monkeypatch.setattr("app.websocket.redis_bridge.publish_event", fake_publish)
    await manager.broadcast("tenant_a", "queue:update", {"event": "token_called"})

    assert published == [("tenant_a", "queue:update", {"event": "token_called"})]
    assert socket.messages == []


@pytest.mark.asyncio
async def test_broadcast_local_is_tenant_isolated():
    manager = WebSocketManager()
    tenant_a_socket = FakeWebSocket()
    tenant_b_socket = FakeWebSocket()
    await manager.connect(tenant_a_socket, "tenant_a", "visit:update")
    await manager.connect(tenant_b_socket, "tenant_b", "visit:update")

    await manager.broadcast_local("tenant_a", "visit:update", {"event": "consultation_started"})

    assert len(tenant_a_socket.messages) == 1
    assert tenant_b_socket.messages == []


def test_event_channels_match_websocket_contract():
    assert {
        "queue:update", "appointment:update", "visit:update", "pharmacy:update",
        "lab:update", "pos:payment", "indent:update",
    } == set(ALLOWED_EVENT_CHANNELS)


def test_invalid_event_routes_are_rejected():
    with pytest.raises(ValueError):
        WebSocketManager._validate_route("tenant-a", "queue:update")
    with pytest.raises(ValueError):
        WebSocketManager._validate_route("tenant_a", "billing:update")