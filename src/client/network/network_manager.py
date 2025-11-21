"""Network manager orchestrating all network components."""

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable

import aiohttp

from .heartbeat import HeartbeatManager
from .rate_limiter import RestRateLimiter
from .sequence_tracker import SequenceTracker, Gap
from .reconciler import Reconciler

try:
    from ..config import ClientConfig
except ImportError:
    # Fallback for direct import
    from ...client.config import ClientConfig


logger = logging.getLogger(__name__)


class NetworkManager:
    """Orchestrates all network management components."""

    def __init__(
        self,
        base_url: str,
        session_id: str,
        config: Optional[ClientConfig] = None,
    ):
        """Initialize network manager.

        Args:
            base_url: Server base URL
            session_id: Session ID for requests
            config: Client configuration
        """
        if config is None:
            from ..config import ClientConfig

            config = ClientConfig()

        self.base_url = base_url
        self.ws_url = base_url.replace("http", "ws") + "/ws"
        self.session_id = session_id
        self.config = config

        # Initialize components
        self.rate_limiter = RestRateLimiter(
            proactive=config.network.rate_limit_proactive,
            initial_backoff=config.network.rate_limit_initial_backoff,
            max_backoff=config.network.rate_limit_max_backoff,
            backoff_multiplier=config.network.rate_limit_backoff_multiplier,
        )

        self.sequence_tracker = SequenceTracker()

        self.reconciler = Reconciler(
            base_url=base_url,
            session_id=session_id,
            rate_limiter=self.rate_limiter,
            on_market_data_reconciled=self._on_market_data_reconciled,
            on_price_history_reconciled=self._on_price_history_reconciled,
            on_orders_reconciled=self._on_orders_reconciled,
            on_balance_reconciled=self._on_balance_reconciled,
        )

        self.heartbeat = HeartbeatManager(
            interval=config.network.heartbeat_interval,
            timeout=config.network.heartbeat_timeout,
            on_health_change=self._on_heartbeat_health_change,
        )

        # Connection state
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._ws_connected = False
        self._connection_healthy = True
        self._subscriptions: Dict[str, set[str]] = defaultdict(set)
        self._subscribed_symbols: set[str] = set()
        self._last_market_timestamps: Dict[str, datetime] = {}
        self._connection_recovery_task: Optional[asyncio.Task] = None
        self._activity_monitor_task: Optional[asyncio.Task] = None
        self._last_ws_message_time: datetime = datetime.now(timezone.utc)

        # Callbacks
        self._on_ws_message: Optional[Callable[[Dict[str, Any]], None]] = None
        self._on_reconciliation: Optional[Callable[[str, Any], None]] = None
        self._on_connection_change: Optional[Callable[[bool], None]] = None

    async def connect_ws(self) -> bool:
        """Connect to WebSocket and start heartbeat.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            if self._http_session is None or self._http_session.closed:
                self._http_session = aiohttp.ClientSession()

            self._ws = await self._http_session.ws_connect(self.ws_url)
            self._ws_connected = True
            self._last_ws_message_time = datetime.now(timezone.utc)
            await self.heartbeat.start(self._ws)
            self._start_activity_monitor()
            logger.info("WebSocket connected")
            return True
        except Exception as e:
            self._ws_connected = False
            logger.error(f"WebSocket connection failed: {e}")
            return False

    async def disconnect_ws(self) -> None:
        """Disconnect WebSocket and stop heartbeat."""
        await self._stop_activity_monitor()
        await self.heartbeat.stop()
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        self._ws_connected = False

    async def send_ws_message(self, message: dict) -> bool:
        """Send WebSocket message.

        Args:
            message: Message dictionary

        Returns:
            True if sent successfully, False otherwise
        """
        msg_type = message.get("type")
        if msg_type == "SUBSCRIBE":
            channel = message.get("channel")
            symbol = message.get("symbol")
            if channel and symbol:
                self._subscriptions[channel].add(symbol)
                self._subscribed_symbols.add(symbol)
        elif msg_type == "UNSUBSCRIBE":
            channel = message.get("channel")
            symbol = message.get("symbol")
            if channel and symbol:
                self._subscriptions[channel].discard(symbol)
                self._subscribed_symbols.discard(symbol)

        if not self._ws or self._ws.closed:
            logger.warning("Cannot send WS message; connection not available")
            return False

        try:
            await self._ws.send_str(json.dumps(message))
            return True
        except Exception as e:
            logger.error(f"WebSocket send failed: {e}")
            return False

    async def receive_ws_message(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Receive WebSocket message and track sequences.

        Args:
            timeout: Timeout in seconds (None = no timeout)

        Returns:
            Message dictionary or None if timeout/error
        """
        if not self._ws or self._ws.closed:
            return None

        try:
            if timeout:
                msg = await asyncio.wait_for(self._ws.receive(), timeout=timeout)
            else:
                msg = await self._ws.receive()

            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                self._last_ws_message_time = datetime.now(timezone.utc)

                # Handle PONG
                if data.get("type") == "PONG":
                    request_id = data.get("request_id")
                    if request_id:
                        await self.heartbeat.handle_pong(request_id)

                # Track sequences for MARKET_DATA messages
                if data.get("type") == "MARKET_DATA" and self.config.network.reconciliation_enabled:
                    symbol = data.get("symbol", "")
                    sequence_id = data.get("sequence_id")
                    if sequence_id is not None:
                        gap = self.sequence_tracker.update("TICKER", symbol, sequence_id)
                        if gap:
                            # Trigger reconciliation asynchronously
                            asyncio.create_task(
                                self.reconciler.reconcile_market_data(symbol, gap)
                            )
                    timestamp = self._parse_timestamp(data.get("timestamp"))
                    if timestamp and symbol:
                        self._last_market_timestamps[symbol] = timestamp

                # Call message handler
                if self._on_ws_message:
                    self._on_ws_message(data)

                return data

            elif msg.type == aiohttp.WSMsgType.CLOSED:
                self._ws_connected = False
                logger.warning("WebSocket closed by server")
                await self._handle_silent_connection()
                return None
            elif msg.type == aiohttp.WSMsgType.ERROR:
                self._ws_connected = False
                logger.error(f"WebSocket error: {msg}")
                return None

        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"WebSocket receive error: {e}")
            return None

        return None

    async def rest_request(
        self, method: str, endpoint: str, **kwargs
    ) -> Optional[aiohttp.ClientResponse]:
        """Make REST API request with rate limiting.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            endpoint: API endpoint path
            **kwargs: Additional arguments for aiohttp request

        Returns:
            Response object or None if failed
        """
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()

        headers = kwargs.pop("headers", {})
        headers["X-Session-ID"] = self.session_id

        async def make_request():
            full_url = f"{self.base_url}{endpoint}"
            logger.info("REST %s %s", method.upper(), full_url)
            return await self._http_session.request(
                method, full_url, headers=headers, **kwargs
            )

        try:
            response = await self.rate_limiter.retry_request(
                make_request, endpoint, max_retries=3
            )
            return response
        except Exception as e:
            logger.error(f"REST request failed: {e}")
            return None

    async def reconcile(self) -> None:
        """Trigger full reconciliation."""
        if self.config.network.reconciliation_enabled:
            await self.reconciler.reconcile_all()

    def get_connection_health(self) -> Dict[str, Any]:
        """Get connection health status.

        Returns:
            Dictionary with health information
        """
        return {
            "ws_connected": self._ws_connected and self.heartbeat.is_healthy(),
            "heartbeat_healthy": self.heartbeat.is_healthy(),
            "connection_healthy": self._connection_healthy,
        }

    def _parse_timestamp(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        ts_str = value
        if ts_str.endswith("Z"):
            ts_str = ts_str.replace("Z", "+00:00")
        elif "+" not in ts_str and ts_str.count("-") <= 2:
            ts_str = ts_str + "+00:00"
        try:
            return datetime.fromisoformat(ts_str)
        except ValueError:
            return None

    def set_on_ws_message(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Set callback for WebSocket messages.

        Args:
            callback: Function to call with each message
        """
        self._on_ws_message = callback

    def set_on_reconciliation(
        self, callback: Callable[[str, Any], None]
    ) -> None:
        """Set callback for reconciliation events.

        Args:
            callback: Function to call with (type, data) on reconciliation
        """
        self._on_reconciliation = callback

    def set_on_connection_change(
        self, callback: Callable[[bool], None]
    ) -> None:
        """Set callback for connection state changes.

        Args:
            callback: Function to call with connection state (True=connected, False=disconnected)
        """
        self._on_connection_change = callback

    def _on_market_data_reconciled(self, symbol: str, data: Dict[str, Any]) -> None:
        """Handle market data reconciliation."""
        if self._on_reconciliation:
            self._on_reconciliation("market_data", {"symbol": symbol, "data": data})

    def _on_price_history_reconciled(
        self, symbol: str, prices: list[Dict[str, Any]]
    ) -> None:
        logger.info(
            "Price history reconciled for %s (%d points)", symbol, len(prices)
        )
        latest_ts = None
        for point in prices:
            ts = self._parse_timestamp(point.get("timestamp"))
            if ts and (latest_ts is None or ts > latest_ts):
                latest_ts = ts
        if latest_ts:
            self._last_market_timestamps[symbol] = latest_ts
        if self._on_reconciliation:
            self._on_reconciliation(
                "price_history", {"symbol": symbol, "prices": prices}
            )

    def _on_orders_reconciled(self, orders: list) -> None:
        """Handle orders reconciliation."""
        if self._on_reconciliation:
            self._on_reconciliation("orders", orders)

    def _on_balance_reconciled(self, balances: Dict[str, str]) -> None:
        """Handle balance reconciliation."""
        if self._on_reconciliation:
            self._on_reconciliation("balance", balances)

    def _on_heartbeat_health_change(self, healthy: bool) -> None:
        """Handle heartbeat health change."""
        self._connection_healthy = healthy
        if not healthy:
            self._ws_connected = False
            # Notify dashboard of connection loss immediately
            if self._on_connection_change:
                self._on_connection_change(False)
            if (
                self._connection_recovery_task is None
                or self._connection_recovery_task.done()
            ):
                logger.warning("Heartbeat unhealthy; initiating silent-connection handler")
                self._connection_recovery_task = asyncio.create_task(
                    self._handle_silent_connection()
                )

    async def _handle_silent_connection(self) -> None:
        """Handle silent WebSocket connections by disconnecting and backfilling."""
        try:
            await self.disconnect_ws()
            await self._backfill_price_history()
            await self._attempt_reconnect()
        except Exception as exc:
            logger.error(f"Silent connection handling failed: {exc}")
        finally:
            self._connection_recovery_task = None

    async def _backfill_price_history(self) -> None:
        """Fetch missing market data for subscribed symbols."""
        if not self.config.network.reconciliation_enabled:
            return

        symbols = set(self._subscribed_symbols)
        for symbol_set in self._subscriptions.values():
            symbols.update(symbol_set)

        if not symbols:
            logger.info("No subscribed symbols to backfill")
            return

        tasks = []
        now = datetime.now(timezone.utc)
        limit = self.config.network.price_history_limit
        for symbol in symbols:
            start = self._last_market_timestamps.get(symbol)
            tasks.append(
                self.reconciler.reconcile_price_history(
                    symbol, start=start, end=now, limit=limit
                )
            )

        logger.info(
            "Requesting price history for %d symbol(s): %s",
            len(symbols),
            list(symbols),
        )
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _attempt_reconnect(self) -> None:
        """Try to re-establish the WebSocket connection with backoff."""
        attempts = 0
        delay = self.config.network.reconnect_initial_backoff
        max_delay = self.config.network.reconnect_max_backoff
        max_attempts = self.config.network.reconnect_max_attempts

        while attempts < max_attempts:
            attempts += 1
            logger.info("Attempting WS reconnect (attempt %d/%d)", attempts, max_attempts)
            if await self.connect_ws():
                self._connection_healthy = True
                await self._resubscribe_channels()
                logger.info("WebSocket reconnect successful")
                # Notify dashboard of connection restoration
                if self._on_connection_change:
                    self._on_connection_change(True)
                self._connection_recovery_task = None
                return

            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)

        logger.error("Failed to reconnect after silent connection.")
        self._connection_recovery_task = None

    async def _resubscribe_channels(self) -> None:
        """Re-subscribe to all known channels/symbols after reconnect."""
        if not self._ws or self._ws.closed:
            return

        for channel, symbols in list(self._subscriptions.items()):
            for symbol in list(symbols):
                msg = {
                    "type": "SUBSCRIBE",
                    "channel": channel,
                    "symbol": symbol,
                    "request_id": f"resub_{uuid.uuid4()}",
                }
                await self.send_ws_message(msg)

    def _start_activity_monitor(self) -> None:
        if (
            self._activity_monitor_task is None
            or self._activity_monitor_task.done()
        ):
            self._activity_monitor_task = asyncio.create_task(
                self._monitor_ws_activity()
            )

    async def _stop_activity_monitor(self) -> None:
        if self._activity_monitor_task:
            self._activity_monitor_task.cancel()
            try:
                await self._activity_monitor_task
            except asyncio.CancelledError:
                pass
            self._activity_monitor_task = None

    async def _monitor_ws_activity(self) -> None:
        """Detect silent connections faster than heartbeat interval."""
        idle_timeout = self.config.network.ws_idle_timeout
        try:
            while True:
                await asyncio.sleep(max(0.5, idle_timeout / 2))
                if not self._ws_connected:
                    break
                elapsed = (
                    datetime.now(timezone.utc) - self._last_ws_message_time
                ).total_seconds()
                if elapsed > idle_timeout:
                    logger.warning(
                        "WS idle for %.2fs (> %.2fs). Treating as silent.",
                        elapsed,
                        idle_timeout,
                    )
                    await self._handle_silent_connection()
                    break
        except asyncio.CancelledError:
            pass

    async def close(self) -> None:
        """Close all connections."""
        await self.disconnect_ws()
        await self.reconciler.close()
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

