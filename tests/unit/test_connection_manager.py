"""Tests for connection manager."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from src.exchange_simulator.connection_manager import ConnectionManager, SessionState


class TestConnectionManager:
    """Test cases for ConnectionManager."""

    @pytest.fixture
    def manager(self) -> ConnectionManager:
        """Create a connection manager for testing."""
        return ConnectionManager()

    @pytest.fixture
    def mock_websocket(self) -> MagicMock:
        """Create a mock WebSocket."""
        ws = MagicMock()
        ws.send = AsyncMock()
        ws.close = AsyncMock()
        return ws

    async def test_add_connection(self, manager: ConnectionManager, mock_websocket: MagicMock) -> None:
        """Test adding a connection."""
        session_id = await manager.add_connection(mock_websocket)

        assert session_id is not None
        assert len(session_id) > 0
        assert manager.get_connection(session_id) == mock_websocket
        assert manager.get_session_count() == 1

    async def test_add_multiple_connections(
        self, manager: ConnectionManager, mock_websocket: MagicMock
    ) -> None:
        """Test adding multiple connections."""
        ws1 = mock_websocket
        ws2 = MagicMock()
        ws2.send = AsyncMock()

        session_id1 = await manager.add_connection(ws1)
        session_id2 = await manager.add_connection(ws2)

        assert session_id1 != session_id2
        assert manager.get_session_count() == 2
        assert manager.get_connection(session_id1) == ws1
        assert manager.get_connection(session_id2) == ws2

    async def test_remove_connection(self, manager: ConnectionManager, mock_websocket: MagicMock) -> None:
        """Test removing a connection."""
        session_id = await manager.add_connection(mock_websocket)
        assert manager.get_session_count() == 1

        await manager.remove_connection(session_id)

        assert manager.get_connection(session_id) is None
        assert manager.get_session(session_id) is None
        assert manager.get_session_count() == 0

    async def test_remove_nonexistent_connection(self, manager: ConnectionManager) -> None:
        """Test removing a nonexistent connection (should not raise error)."""
        await manager.remove_connection("nonexistent")
        assert manager.get_session_count() == 0

    async def test_get_session(self, manager: ConnectionManager, mock_websocket: MagicMock) -> None:
        """Test getting session state."""
        session_id = await manager.add_connection(mock_websocket)
        session = manager.get_session(session_id)

        assert session is not None
        assert session.session_id == session_id
        assert isinstance(session.connected_at, datetime)
        assert isinstance(session.last_activity, datetime)
        assert session.subscriptions == set()
        assert session.is_authenticated is False

    async def test_update_activity(self, manager: ConnectionManager, mock_websocket: MagicMock) -> None:
        """Test updating activity timestamp."""
        session_id = await manager.add_connection(mock_websocket)
        original_session = manager.get_session(session_id)
        original_time = original_session.last_activity

        # Small delay to ensure timestamp changes
        import asyncio
        await asyncio.sleep(0.01)

        await manager.update_activity(session_id)
        updated_session = manager.get_session(session_id)

        assert updated_session.last_activity > original_time

    async def test_add_subscription(self, manager: ConnectionManager, mock_websocket: MagicMock) -> None:
        """Test adding a subscription."""
        session_id = await manager.add_connection(mock_websocket)

        result = await manager.add_subscription(session_id, "TRADES:BTC/USD")
        assert result is True

        session = manager.get_session(session_id)
        assert "TRADES:BTC/USD" in session.subscriptions

    async def test_add_multiple_subscriptions(
        self, manager: ConnectionManager, mock_websocket: MagicMock
    ) -> None:
        """Test adding multiple subscriptions."""
        session_id = await manager.add_connection(mock_websocket)

        await manager.add_subscription(session_id, "TRADES:BTC/USD")
        await manager.add_subscription(session_id, "ORDERBOOK:BTC/USD")

        session = manager.get_session(session_id)
        assert len(session.subscriptions) == 2
        assert "TRADES:BTC/USD" in session.subscriptions
        assert "ORDERBOOK:BTC/USD" in session.subscriptions

    async def test_add_subscription_nonexistent_session(self, manager: ConnectionManager) -> None:
        """Test adding subscription to nonexistent session."""
        result = await manager.add_subscription("nonexistent", "TRADES:BTC/USD")
        assert result is False

    async def test_remove_subscription(self, manager: ConnectionManager, mock_websocket: MagicMock) -> None:
        """Test removing a subscription."""
        session_id = await manager.add_connection(mock_websocket)
        await manager.add_subscription(session_id, "TRADES:BTC/USD")

        result = await manager.remove_subscription(session_id, "TRADES:BTC/USD")
        assert result is True

        session = manager.get_session(session_id)
        assert "TRADES:BTC/USD" not in session.subscriptions

    async def test_remove_nonexistent_subscription(
        self, manager: ConnectionManager, mock_websocket: MagicMock
    ) -> None:
        """Test removing a subscription that doesn't exist."""
        session_id = await manager.add_connection(mock_websocket)

        result = await manager.remove_subscription(session_id, "TRADES:BTC/USD")
        assert result is True  # Should succeed even if subscription doesn't exist

        session = manager.get_session(session_id)
        assert len(session.subscriptions) == 0

    async def test_get_subscribed_sessions(
        self, manager: ConnectionManager, mock_websocket: MagicMock
    ) -> None:
        """Test getting sessions subscribed to a channel."""
        ws1 = mock_websocket
        ws2 = MagicMock()
        ws2.send = AsyncMock()
        ws3 = MagicMock()
        ws3.send = AsyncMock()

        session_id1 = await manager.add_connection(ws1)
        session_id2 = await manager.add_connection(ws2)
        session_id3 = await manager.add_connection(ws3)

        await manager.add_subscription(session_id1, "TRADES:BTC/USD")
        await manager.add_subscription(session_id2, "TRADES:BTC/USD")
        await manager.add_subscription(session_id3, "ORDERBOOK:BTC/USD")

        subscribed = manager.get_subscribed_sessions("TRADES:BTC/USD")

        assert len(subscribed) == 2
        assert session_id1 in subscribed
        assert session_id2 in subscribed
        assert session_id3 not in subscribed

    async def test_send_to_session(self, manager: ConnectionManager, mock_websocket: MagicMock) -> None:
        """Test sending a message to a session."""
        session_id = await manager.add_connection(mock_websocket)

        result = await manager.send_to_session(session_id, '{"type": "TEST"}')

        assert result is True
        mock_websocket.send.assert_called_once_with('{"type": "TEST"}')

    async def test_send_to_nonexistent_session(self, manager: ConnectionManager) -> None:
        """Test sending to a nonexistent session."""
        result = await manager.send_to_session("nonexistent", '{"type": "TEST"}')
        assert result is False

    async def test_send_to_session_connection_error(
        self, manager: ConnectionManager, mock_websocket: MagicMock
    ) -> None:
        """Test sending to a session with connection error."""
        session_id = await manager.add_connection(mock_websocket)
        mock_websocket.send.side_effect = Exception("Connection closed")

        result = await manager.send_to_session(session_id, '{"type": "TEST"}')

        assert result is False

    async def test_broadcast(self, manager: ConnectionManager) -> None:
        """Test broadcasting to all sessions."""
        ws1 = MagicMock()
        ws1.send = AsyncMock()
        ws2 = MagicMock()
        ws2.send = AsyncMock()
        ws3 = MagicMock()
        ws3.send = AsyncMock()

        await manager.add_connection(ws1)
        await manager.add_connection(ws2)
        await manager.add_connection(ws3)

        count = await manager.broadcast('{"type": "BROADCAST"}')

        assert count == 3
        ws1.send.assert_called_once()
        ws2.send.assert_called_once()
        ws3.send.assert_called_once()

    async def test_broadcast_with_exclude(self, manager: ConnectionManager) -> None:
        """Test broadcasting with exclusion list."""
        ws1 = MagicMock()
        ws1.send = AsyncMock()
        ws2 = MagicMock()
        ws2.send = AsyncMock()
        ws3 = MagicMock()
        ws3.send = AsyncMock()

        session_id1 = await manager.add_connection(ws1)
        await manager.add_connection(ws2)
        await manager.add_connection(ws3)

        count = await manager.broadcast('{"type": "BROADCAST"}', exclude={session_id1})

        assert count == 2
        ws1.send.assert_not_called()
        ws2.send.assert_called_once()
        ws3.send.assert_called_once()

    async def test_broadcast_to_channel(self, manager: ConnectionManager) -> None:
        """Test broadcasting to a channel."""
        ws1 = MagicMock()
        ws1.send = AsyncMock()
        ws2 = MagicMock()
        ws2.send = AsyncMock()
        ws3 = MagicMock()
        ws3.send = AsyncMock()

        session_id1 = await manager.add_connection(ws1)
        session_id2 = await manager.add_connection(ws2)
        await manager.add_connection(ws3)

        await manager.add_subscription(session_id1, "TRADES:BTC/USD")
        await manager.add_subscription(session_id2, "TRADES:BTC/USD")

        count = await manager.broadcast_to_channel("TRADES:BTC/USD", '{"type": "TRADE"}')

        assert count == 2
        ws1.send.assert_called_once()
        ws2.send.assert_called_once()
        ws3.send.assert_not_called()

    async def test_get_active_sessions(self, manager: ConnectionManager) -> None:
        """Test getting active sessions."""
        ws1 = MagicMock()
        ws2 = MagicMock()

        session_id1 = await manager.add_connection(ws1)
        session_id2 = await manager.add_connection(ws2)

        active = manager.get_active_sessions()

        assert len(active) == 2
        assert session_id1 in active
        assert session_id2 in active

    async def test_close_session(self, manager: ConnectionManager, mock_websocket: MagicMock) -> None:
        """Test closing a session."""
        session_id = await manager.add_connection(mock_websocket)

        await manager.close_session(session_id, code=1000, reason="Normal close")

        mock_websocket.close.assert_called_once_with(1000, "Normal close")
        assert manager.get_connection(session_id) is None
        assert manager.get_session_count() == 0

    async def test_close_nonexistent_session(self, manager: ConnectionManager) -> None:
        """Test closing a nonexistent session (should not raise error)."""
        await manager.close_session("nonexistent")

    async def test_close_all(self, manager: ConnectionManager) -> None:
        """Test closing all sessions."""
        ws1 = MagicMock()
        ws1.close = AsyncMock()
        ws2 = MagicMock()
        ws2.close = AsyncMock()

        await manager.add_connection(ws1)
        await manager.add_connection(ws2)

        await manager.close_all()

        assert manager.get_session_count() == 0
        ws1.close.assert_called_once()
        ws2.close.assert_called_once()
