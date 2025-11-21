"""WebSocket heartbeat management."""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, Callable


class HeartbeatManager:
    """Manages WebSocket heartbeat (PING/PONG) for connection health monitoring."""

    def __init__(
        self,
        interval: float = 60.0,
        timeout: float = 10.0,
        on_health_change: Optional[Callable[[bool], None]] = None,
    ):
        """Initialize heartbeat manager.

        Args:
            interval: PING interval in seconds (default: 60)
            timeout: PONG timeout in seconds (default: 10)
            on_health_change: Callback when connection health changes
        """
        self.interval = interval
        self.timeout = timeout
        self.on_health_change = on_health_change

        self._ws = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._pending_pings: Dict[str, datetime] = {}
        self._lock = asyncio.Lock()
        self._healthy = True

    async def start(self, ws_connection) -> None:
        """Start heartbeat loop.

        Args:
            ws_connection: WebSocket connection object
        """
        async with self._lock:
            self._ws = ws_connection
            if self._running:
                return
            self._running = True
            self._task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        """Stop heartbeat loop."""
        async with self._lock:
            self._running = False
            if self._task:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._pending_pings.clear()

    async def handle_pong(self, request_id: str) -> None:
        """Handle PONG response.

        Args:
            request_id: Request ID from PONG message
        """
        async with self._lock:
            if request_id in self._pending_pings:
                del self._pending_pings[request_id]
                if not self._healthy:
                    self._healthy = True
                    if self.on_health_change:
                        self.on_health_change(True)

    def is_healthy(self) -> bool:
        """Check if heartbeat is responding.

        Returns:
            True if connection is healthy, False otherwise
        """
        return self._healthy

    async def _heartbeat_loop(self) -> None:
        """Main heartbeat loop."""
        while self._running:
            try:
                await asyncio.sleep(self.interval)

                if not self._running:
                    break

                async with self._lock:
                    if not self._ws or self._ws.closed:
                        break

                    # Send PING
                    request_id = str(uuid.uuid4())
                    ping_msg = {
                        "type": "PING",
                        "request_id": request_id,
                    }

                    try:
                        await self._ws.send_str(json.dumps(ping_msg))
                        self._pending_pings[request_id] = datetime.now()

                        # Schedule timeout check
                        asyncio.create_task(self._check_pong_timeout(request_id))

                    except Exception as e:
                        # Connection error
                        if self._healthy:
                            self._healthy = False
                            if self.on_health_change:
                                self.on_health_change(False)
                        break

            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log error and continue
                if self._healthy:
                    self._healthy = False
                    if self.on_health_change:
                        self.on_health_change(False)
                await asyncio.sleep(1)

    async def _check_pong_timeout(self, request_id: str) -> None:
        """Check if PONG was received within timeout."""
        await asyncio.sleep(self.timeout)

        async with self._lock:
            if request_id in self._pending_pings:
                # PONG not received within timeout
                del self._pending_pings[request_id]
                if self._healthy:
                    self._healthy = False
                    if self.on_health_change:
                        self.on_health_change(False)

