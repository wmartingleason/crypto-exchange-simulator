"""Tests for client heartbeat functionality."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from src.client.network.heartbeat import HeartbeatManager


class TestHeartbeatManager:
    """Test cases for HeartbeatManager."""

    @pytest.fixture
    def mock_ws(self):
        """Create a mock WebSocket connection."""
        ws = AsyncMock()
        ws.closed = False
        ws.send_str = AsyncMock()
        return ws

    @pytest.fixture
    def heartbeat(self):
        """Create a heartbeat manager with short intervals for testing."""
        return HeartbeatManager(interval=0.1, timeout=0.05)

    @pytest.mark.asyncio
    async def test_start_stop(self, heartbeat: HeartbeatManager, mock_ws):
        """Test starting and stopping heartbeat."""
        await heartbeat.start(mock_ws)
        assert heartbeat.is_healthy()

        await asyncio.sleep(0.15)  # Wait for at least one PING
        assert mock_ws.send_str.called

        await heartbeat.stop()
        assert not heartbeat._running

    @pytest.mark.asyncio
    async def test_ping_sent(self, heartbeat: HeartbeatManager, mock_ws):
        """Test that PING messages are sent periodically."""
        await heartbeat.start(mock_ws)

        await asyncio.sleep(0.15)  # Wait for PING
        assert mock_ws.send_str.called

        call_args = mock_ws.send_str.call_args[0][0]
        import json
        ping_data = json.loads(call_args)
        assert ping_data["type"] == "PING"
        assert "request_id" in ping_data

        await heartbeat.stop()

    @pytest.mark.asyncio
    async def test_pong_handling(self, heartbeat: HeartbeatManager, mock_ws):
        """Test that PONG responses are handled correctly."""
        await heartbeat.start(mock_ws)

        await asyncio.sleep(0.15)  # Wait for PING
        assert mock_ws.send_str.called

        call_args = mock_ws.send_str.call_args[0][0]
        import json
        ping_data = json.loads(call_args)
        request_id = ping_data["request_id"]

        await heartbeat.handle_pong(request_id)
        assert heartbeat.is_healthy()

        await heartbeat.stop()

    @pytest.mark.asyncio
    async def test_pong_timeout(self, heartbeat: HeartbeatManager, mock_ws):
        """Test that missing PONG triggers unhealthy state."""
        health_changes = []

        def on_health_change(healthy: bool):
            health_changes.append(healthy)

        heartbeat.on_health_change = on_health_change
        await heartbeat.start(mock_ws)

        await asyncio.sleep(0.15)  # Wait for PING
        assert mock_ws.send_str.called

        await asyncio.sleep(0.1)  # Wait for timeout
        assert not heartbeat.is_healthy()
        assert False in health_changes

        await heartbeat.stop()

    @pytest.mark.asyncio
    async def test_health_change_callback(self, heartbeat: HeartbeatManager, mock_ws):
        """Test health change callback is called."""
        health_states = []

        def on_health_change(healthy: bool):
            health_states.append(healthy)

        heartbeat.on_health_change = on_health_change
        await heartbeat.start(mock_ws)

        await asyncio.sleep(0.15)  # Wait for PING
        call_args = mock_ws.send_str.call_args[0][0]
        import json
        ping_data = json.loads(call_args)
        request_id = ping_data["request_id"]

        # Don't respond to PING - wait for timeout
        await asyncio.sleep(0.1)  # Wait for timeout

        # Should have received unhealthy callback
        assert len(health_states) > 0
        assert False in health_states

        await heartbeat.stop()

