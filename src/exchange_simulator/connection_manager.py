"""Connection manager for WebSocket connections."""

import asyncio
import uuid
from typing import Dict, Optional, Set
from datetime import datetime
from websockets.server import WebSocketServerProtocol
from pydantic import BaseModel


class SessionState(BaseModel):
    """State information for a client session."""

    session_id: str
    connected_at: datetime
    last_activity: datetime
    subscriptions: Set[str] = set()
    is_authenticated: bool = False

    class Config:
        """Pydantic config."""
        arbitrary_types_allowed = True


class ConnectionManager:
    """Manages WebSocket connections and session state."""

    def __init__(self) -> None:
        """Initialize the connection manager."""
        self._connections: Dict[str, WebSocketServerProtocol] = {}
        self._sessions: Dict[str, SessionState] = {}
        self._lock = asyncio.Lock()

    async def add_connection(self, websocket: WebSocketServerProtocol) -> str:
        """Add a new WebSocket connection.

        Args:
            websocket: The WebSocket connection to add

        Returns:
            Assigned session ID
        """
        async with self._lock:
            session_id = str(uuid.uuid4())
            now = datetime.utcnow()

            self._connections[session_id] = websocket
            self._sessions[session_id] = SessionState(
                session_id=session_id,
                connected_at=now,
                last_activity=now,
            )

            return session_id

    async def remove_connection(self, session_id: str) -> None:
        """Remove a WebSocket connection.

        Args:
            session_id: Session ID to remove
        """
        async with self._lock:
            self._connections.pop(session_id, None)
            self._sessions.pop(session_id, None)

    def get_connection(self, session_id: str) -> Optional[WebSocketServerProtocol]:
        """Get a WebSocket connection by session ID.

        Args:
            session_id: Session ID to look up

        Returns:
            WebSocket connection or None if not found
        """
        return self._connections.get(session_id)

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """Get session state by session ID.

        Args:
            session_id: Session ID to look up

        Returns:
            Session state or None if not found
        """
        return self._sessions.get(session_id)

    async def update_activity(self, session_id: str) -> None:
        """Update last activity timestamp for a session.

        Args:
            session_id: Session ID to update
        """
        session = self._sessions.get(session_id)
        if session:
            session.last_activity = datetime.utcnow()

    async def add_subscription(self, session_id: str, channel: str) -> bool:
        """Add a subscription to a session.

        Args:
            session_id: Session ID
            channel: Channel to subscribe to

        Returns:
            True if subscription was added, False if session not found
        """
        session = self._sessions.get(session_id)
        if session:
            session.subscriptions.add(channel)
            return True
        return False

    async def remove_subscription(self, session_id: str, channel: str) -> bool:
        """Remove a subscription from a session.

        Args:
            session_id: Session ID
            channel: Channel to unsubscribe from

        Returns:
            True if subscription was removed, False if session not found
        """
        session = self._sessions.get(session_id)
        if session:
            session.subscriptions.discard(channel)
            return True
        return False

    def get_subscribed_sessions(self, channel: str) -> Set[str]:
        """Get all sessions subscribed to a channel.

        Args:
            channel: Channel to check

        Returns:
            Set of session IDs subscribed to the channel
        """
        return {
            session_id
            for session_id, session in self._sessions.items()
            if channel in session.subscriptions
        }

    async def send_to_session(self, session_id: str, message: str) -> bool:
        """Send a message to a specific session.

        Args:
            session_id: Session ID to send to
            message: Message to send (JSON string)

        Returns:
            True if message was sent, False if session not found or send failed
        """
        websocket = self._connections.get(session_id)
        if websocket:
            try:
                await websocket.send(message)
                return True
            except Exception:
                # Connection might be closed
                return False
        return False

    async def broadcast(self, message: str, exclude: Optional[Set[str]] = None) -> int:
        """Broadcast a message to all connected sessions.

        Args:
            message: Message to broadcast (JSON string)
            exclude: Set of session IDs to exclude from broadcast

        Returns:
            Number of sessions that received the message
        """
        exclude = exclude or set()
        sent_count = 0

        for session_id in list(self._connections.keys()):
            if session_id not in exclude:
                if await self.send_to_session(session_id, message):
                    sent_count += 1

        return sent_count

    async def broadcast_to_channel(self, channel: str, message: str) -> int:
        """Broadcast a message to all sessions subscribed to a channel.

        Args:
            channel: Channel to broadcast to
            message: Message to broadcast (JSON string)

        Returns:
            Number of sessions that received the message
        """
        subscribed = self.get_subscribed_sessions(channel)
        sent_count = 0

        for session_id in subscribed:
            if await self.send_to_session(session_id, message):
                sent_count += 1

        return sent_count

    def get_active_sessions(self) -> Set[str]:
        """Get all active session IDs.

        Returns:
            Set of active session IDs
        """
        return set(self._connections.keys())

    def get_session_count(self) -> int:
        """Get the number of active sessions.

        Returns:
            Number of active sessions
        """
        return len(self._connections)

    async def close_session(self, session_id: str, code: int = 1000, reason: str = "") -> None:
        """Close a session gracefully.

        Args:
            session_id: Session ID to close
            code: WebSocket close code
            reason: Close reason
        """
        websocket = self._connections.get(session_id)
        if websocket:
            try:
                await websocket.close(code, reason)
            except Exception:
                pass
            finally:
                await self.remove_connection(session_id)

    async def close_all(self) -> None:
        """Close all active connections."""
        session_ids = list(self._connections.keys())
        for session_id in session_ids:
            await self.close_session(session_id, code=1001, reason="Server shutdown")
