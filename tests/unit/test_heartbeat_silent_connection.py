"""Integration test for heartbeat with silent connection failure mode."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.client.network.heartbeat import HeartbeatManager
from src.exchange_simulator.failures.strategies import SilentConnectionStrategy, FailureContext


class TestHeartbeatWithSilentConnection:
    """Test heartbeat detection of silent connection failures."""

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
    async def test_heartbeat_detects_silent_connection(
        self, heartbeat: HeartbeatManager, mock_ws
    ):
        """Test that heartbeat detects when server stops sending PONG."""
        health_changes = []

        def on_health_change(healthy: bool):
            health_changes.append(healthy)

        heartbeat.on_health_change = on_health_change
        await heartbeat.start(mock_ws)

        # Wait for first PING
        await asyncio.sleep(0.15)
        assert mock_ws.send_str.called

        # Simulate server going silent - don't respond to PING
        await asyncio.sleep(0.1)  # Wait for timeout

        # Heartbeat should detect unhealthy connection
        assert not heartbeat.is_healthy()
        assert False in health_changes

        await heartbeat.stop()

    @pytest.mark.asyncio
    async def test_heartbeat_recovers_when_pong_received(
        self, heartbeat: HeartbeatManager, mock_ws
    ):
        """Test that heartbeat recovers when PONG is received after timeout."""
        health_changes = []

        def on_health_change(healthy: bool):
            health_changes.append(healthy)

        heartbeat.on_health_change = on_health_change
        await heartbeat.start(mock_ws)

        # Wait for first PING
        await asyncio.sleep(0.15)
        assert mock_ws.send_str.called

        # Simulate timeout (no PONG)
        await asyncio.sleep(0.1)
        assert not heartbeat.is_healthy()

        # Get the request_id from the PING
        call_args = mock_ws.send_str.call_args[0][0]
        import json
        ping_data = json.loads(call_args)
        request_id = ping_data["request_id"]

        # Simulate PONG arriving (late, but still valid)
        await heartbeat.handle_pong(request_id)

        # Should recover
        assert heartbeat.is_healthy()
        assert True in health_changes

        await heartbeat.stop()

    @pytest.mark.asyncio
    async def test_silent_connection_blocks_all_messages(self):
        """Test that SilentConnectionStrategy blocks all outbound messages."""
        strategy = SilentConnectionStrategy(enabled=True, after_messages=2)
        context = FailureContext(
            session_id="test",
            message_type="MARKET_DATA",
            direction="outbound",
        )

        # First two messages should pass
        result1 = await strategy.apply("msg1", context)
        assert result1 == "msg1"

        result2 = await strategy.apply("msg2", context)
        assert result2 == "msg2"

        # After that, all messages should be blocked
        result3 = await strategy.apply("msg3", context)
        assert result3 is None

        # PONG should also be blocked
        pong_context = FailureContext(
            session_id="test",
            message_type="PONG",
            direction="outbound",
        )
        import json
        pong_msg = json.dumps({"type": "PONG", "request_id": "test123"})
        result_pong = await strategy.apply(pong_msg, pong_context)
        assert result_pong is None

        assert strategy.dropped_count == 2

