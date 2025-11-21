"""Trading dashboard for exchange simulator."""

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from threading import Thread, Lock
from typing import Any, Optional

import aiohttp
import plotly.graph_objs as go
from dash import Dash, dcc, html
from dash.dependencies import Output, Input


class MarketDataBuffer:
    """Thread-safe buffer for market data."""

    def __init__(self, maxlen=60000):
        self.timestamps = deque(maxlen=maxlen)
        self.prices = deque(maxlen=maxlen)
        self.bids = deque(maxlen=maxlen)
        self.asks = deque(maxlen=maxlen)
        self.volumes = deque(maxlen=maxlen)
        self.lock = Lock()
        self.symbol = None
        self.last_update = None

    def add(self, timestamp, price, bid, ask, volume, symbol):
        with self.lock:
            self.timestamps.append(timestamp)
            self.prices.append(price)
            self.bids.append(bid)
            self.asks.append(ask)
            self.volumes.append(volume)
            self.symbol = symbol
            self.last_update = datetime.now()

    def get(self, max_points=None):
        with self.lock:
            timestamps = list(self.timestamps)
            prices = list(self.prices)
            bids = list(self.bids)
            asks = list(self.asks)
            volumes = list(self.volumes)

            if max_points and len(timestamps) > max_points:
                stride = len(timestamps) // max_points
                timestamps = timestamps[::stride]
                prices = prices[::stride]
                bids = bids[::stride]
                asks = asks[::stride]
                volumes = volumes[::stride]

            return {
                "timestamps": timestamps,
                "prices": prices,
                "bids": bids,
                "asks": asks,
                "volumes": volumes,
                "symbol": self.symbol,
                "last_update": self.last_update,
            }


class AccountState:
    """Thread-safe account state."""

    def __init__(self):
        self.balances = {}
        self.orders = []
        self.lock = Lock()
        self.last_update = None

    def update_balances(self, balances):
        with self.lock:
            self.balances = balances
            self.last_update = datetime.now()

    def update_orders(self, orders):
        with self.lock:
            self.orders = orders
            self.last_update = datetime.now()

    def get(self):
        with self.lock:
            return {
                "balances": dict(self.balances),
                "orders": list(self.orders),
                "last_update": self.last_update,
            }


class ConnectionHealth:
    """Track connection health."""

    def __init__(self):
        self.ws_connected = False
        self.rest_healthy = False
        self.last_ws_message = None
        self.last_rest_check = None
        self.ws_message_count = 0
        self.lock = Lock()

    def ws_message_received(self):
        with self.lock:
            self.ws_connected = True
            self.last_ws_message = datetime.now()
            self.ws_message_count += 1

    def ws_disconnected(self):
        with self.lock:
            self.ws_connected = False

    def rest_check(self, healthy):
        with self.lock:
            self.rest_healthy = healthy
            self.last_rest_check = datetime.now()

    def get(self):
        with self.lock:
            now = datetime.now()
            ws_stale = False
            if self.last_ws_message:
                ws_stale = (now - self.last_ws_message).total_seconds() > 5

            return {
                "ws_connected": self.ws_connected and not ws_stale,
                "rest_healthy": self.rest_healthy,
                "last_ws_message": self.last_ws_message,
                "last_rest_check": self.last_rest_check,
                "ws_message_count": self.ws_message_count,
            }


class CandlestickAggregator:
    """Thread-safe aggregator for converting tick data into OHLCV candlesticks."""

    def __init__(self, interval_seconds: int = 1, max_candles: int = 1000):
        """Initialize candlestick aggregator.

        Args:
            interval_seconds: Time interval for each candle in seconds
            max_candles: Maximum number of candles to store
        """
        self.interval_seconds = interval_seconds
        self.max_candles = max_candles
        self.lock = Lock()
        
        # Current candle being built
        self.current_candle_start = None
        self.current_candle_open = None
        self.current_candle_high = None
        self.current_candle_low = None
        self.current_candle_close = None
        self.current_candle_volume = 0.0
        
        # Completed candles
        self.candles = deque(maxlen=max_candles)

    def _get_candle_start(self, timestamp: datetime) -> datetime:
        """Get the start timestamp for the candle containing this timestamp."""
        if self.interval_seconds == 1:
            # For 1 second intervals, round down to the second
            return timestamp.replace(microsecond=0)
        else:
            # For longer intervals, round down to the interval boundary
            total_seconds = int(timestamp.timestamp())
            interval_start = (total_seconds // self.interval_seconds) * self.interval_seconds
            return datetime.fromtimestamp(interval_start, tz=timestamp.tzinfo)

    def add_tick(self, timestamp: datetime, price: float, volume: float, source: str = "unknown") -> list:
        """Add a tick and return any completed candles.

        Args:
            timestamp: Timestamp of the tick
            price: Price of the tick
            volume: Volume of the tick
            source: Source of the tick (for debugging)

        Returns:
            List of completed candle dictionaries (empty if none completed)
        """
        with self.lock:
            candle_start = self._get_candle_start(timestamp)
            completed_candles = []

            # If we're starting a new candle
            if self.current_candle_start is None or candle_start > self.current_candle_start:
                # If we had a previous candle, finalize it
                if self.current_candle_start is not None:
                    completed_candles.append({
                        "timestamp": self.current_candle_start,
                        "open": self.current_candle_open,
                        "high": self.current_candle_high,
                        "low": self.current_candle_low,
                        "close": self.current_candle_close,
                        "volume": self.current_candle_volume,
                    })
                    self.candles.append(completed_candles[-1])

                    # Log completed candle info
                    if logging.getLogger(__name__).isEnabledFor(logging.DEBUG):
                        candle = completed_candles[-1]
                        spread = candle["high"] - candle["low"]
                        body = abs(candle["close"] - candle["open"])
                        logging.getLogger(__name__).debug(
                            "Completed candle at %s: O=%.2f H=%.2f L=%.2f C=%.2f (spread=%.2f, body=%.2f, ticks=%.0f)",
                            candle["timestamp"], candle["open"], candle["high"],
                            candle["low"], candle["close"], spread, body, candle["volume"] / 0.01
                        )

                # Start new candle
                self.current_candle_start = candle_start
                self.current_candle_open = price
                self.current_candle_high = price
                self.current_candle_low = price
                self.current_candle_close = price
                self.current_candle_volume = volume

                logging.getLogger(__name__).debug(
                    "Started new candle at %s from %s: price=%.2f",
                    candle_start, source, price
                )
            else:
                # Update current candle
                self.current_candle_high = max(self.current_candle_high, price)
                self.current_candle_low = min(self.current_candle_low, price)
                self.current_candle_close = price
                self.current_candle_volume += volume

            return completed_candles

    def get_candles(self, max_candles: int = None) -> list:
        """Get recent candles for display.

        Args:
            max_candles: Maximum number of candles to return

        Returns:
            List of candle dictionaries
        """
        with self.lock:
            candles = list(self.candles)
            if max_candles and len(candles) > max_candles:
                return candles[-max_candles:]
            return candles

    def set_interval(self, interval_seconds: int) -> None:
        """Change the interval and clear existing data.

        Args:
            interval_seconds: New interval in seconds
        """
        with self.lock:
            self.interval_seconds = interval_seconds
            self.candles.clear()
            self.current_candle_start = None
            self.current_candle_open = None
            self.current_candle_high = None
            self.current_candle_low = None
            self.current_candle_close = None
            self.current_candle_volume = 0.0


class TradingDashboard:
    """Trading dashboard with integrated market data and account management."""

    def __init__(
        self,
        base_url: str = "http://localhost:8765",
        symbol: str = "BTC/USD",
        config=None,
    ):
        self.base_url = base_url
        self.ws_url = base_url.replace("http", "ws") + "/ws"
        self.symbol = symbol
        self.session_id = "dashboard"
        self.market_data = MarketDataBuffer()
        self.account = AccountState()
        self.health = ConnectionHealth()
        self.candlestick_aggregator = CandlestickAggregator(interval_seconds=1)
        self.current_interval = 1
        self.running = False
        self.logger = logging.getLogger(__name__)

        # Track the latest timestamp we've processed from ANY source (REST or WS)
        # to avoid processing duplicate data when WS sends backlog after reconnection
        self._latest_processed_timestamp: Optional[datetime] = None

        # Initialize network manager
        from .network.network_manager import NetworkManager
        from .config import ClientConfig

        self.config = config or ClientConfig()
        self.network_manager = NetworkManager(
            base_url=base_url, session_id=self.session_id, config=self.config
        )

        # Set up callbacks
        self.network_manager.set_on_ws_message(self._handle_ws_message)
        self.network_manager.set_on_reconciliation(self._handle_reconciliation)

    def _handle_ws_message(self, data: dict) -> None:
        """Handle WebSocket message from network manager."""
        try:
            self.health.ws_message_received()

            if data.get("type") == "MARKET_DATA":
                timestamp = self._parse_timestamp(data["timestamp"])
                if timestamp is None:
                    self.logger.warning("Received market data with invalid timestamp: %s", data.get("timestamp"))
                    return

                price = float(data["last_price"])

                # Skip if we've already processed this timestamp from any source
                if self._latest_processed_timestamp is not None and timestamp <= self._latest_processed_timestamp:
                    self.logger.debug(
                        "Skipping WS tick at %s (already processed up to %s)",
                        timestamp, self._latest_processed_timestamp
                    )
                    return

                # Use a small volume increment per tick since we don't have actual trade volume
                # This is for visualization purposes only
                tick_volume = 0.01

                self.market_data.add(
                    timestamp,
                    price,
                    float(data["bid"]),
                    float(data["ask"]),
                    float(data["volume_24h"]),
                    data["symbol"],
                )

                # Add tick to candlestick aggregator
                self.candlestick_aggregator.add_tick(timestamp, price, tick_volume, source="WS")

                # Update latest processed timestamp
                self._latest_processed_timestamp = timestamp
        except Exception as e:
            print(f"Error processing WebSocket message: {e}")
            import traceback
            traceback.print_exc()

    def _handle_reconciliation(self, recon_type: str, data: Any) -> None:
        """Handle reconciliation events."""
        if recon_type == "market_data":
            # Market data was reconciled - update if needed
            symbol = data.get("symbol")
            market_data = data.get("data")
            if symbol and market_data:
                # Update market data buffer with reconciled data
                ts_str = market_data.get("timestamp", "")
                if ts_str:
                    if "Z" in ts_str:
                        ts_str = ts_str.replace("Z", "+00:00")
                    elif "+" not in ts_str and ts_str.count("-") <= 2:
                        ts_str = ts_str + "+00:00"
                    timestamp = datetime.fromisoformat(ts_str)
                    price = float(market_data.get("last_price", 0))
                    self.market_data.add(
                        timestamp,
                        price,
                        float(market_data.get("bid", 0)),
                        float(market_data.get("ask", 0)),
                        float(market_data.get("volume_24h", 0)),
                        symbol,
                    )
        elif recon_type == "price_history":
            symbol = data.get("symbol")
            prices = data.get("prices", [])
            if symbol and prices:
                self.logger.info(
                    "Applying %d reconciled price points for %s",
                    len(prices),
                    symbol,
                )
                for point in prices:
                    timestamp = self._parse_timestamp(point.get("timestamp"))
                    if not timestamp:
                        self.logger.warning("Skipping price history entry with invalid timestamp")
                        continue

                    # Skip if we've already processed this timestamp
                    if self._latest_processed_timestamp is not None and timestamp <= self._latest_processed_timestamp:
                        self.logger.debug(
                            "Skipping REST tick at %s (already processed up to %s)",
                            timestamp, self._latest_processed_timestamp
                        )
                        continue

                    price = float(point.get("price", 0))
                    bid = float(point.get("bid", 0))
                    ask = float(point.get("ask", 0))
                    volume = float(point.get("volume_24h", 0))
                    self.market_data.add(timestamp, price, bid, ask, volume, symbol)
                    self.candlestick_aggregator.add_tick(timestamp, price, 0.01, source="REST")

                    # Update latest processed timestamp
                    self._latest_processed_timestamp = timestamp
        elif recon_type == "orders":
            # Orders were reconciled
            self.account.update_orders(data)
        elif recon_type == "balance":
            # Balance was reconciled
            self.account.update_balances(data)

    async def start_websocket(self):
        while self.running:
            try:
                if await self.network_manager.connect_ws():
                    subscribe_msg = {
                        "type": "SUBSCRIBE",
                        "channel": "TICKER",
                        "symbol": self.symbol,
                        "request_id": "dashboard_sub",
                    }
                    await self.network_manager.send_ws_message(subscribe_msg)

                    while self.running:
                        msg = await self.network_manager.receive_ws_message(timeout=1.0)
                        if msg is None:
                            # Check connection health
                            health = self.network_manager.get_connection_health()
                            if not health.get("ws_connected"):
                                break
                            continue

            except Exception as e:
                self.health.ws_disconnected()
                print(f"WebSocket error: {e}")

            if self.running:
                await self.network_manager.disconnect_ws()
                await asyncio.sleep(1)

    def _parse_timestamp(self, value: str) -> Optional[datetime]:
        """Parse ISO timestamp strings."""
        if not value:
            return None
        ts_str = value
        if "Z" in ts_str:
            ts_str = ts_str.replace("Z", "+00:00")
        elif "+" not in ts_str and ts_str.count("-") <= 2:
            ts_str = ts_str + "+00:00"
        try:
            return datetime.fromisoformat(ts_str)
        except ValueError:
            return None

    async def update_account_state(self):
        """Periodically fetch account state via REST."""
        while self.running:
            try:
                # Health check
                health_resp = await self.network_manager.rest_request("GET", "/health")
                self.health.rest_check(health_resp is not None and health_resp.status == 200)

                # Balance
                balance_resp = await self.network_manager.rest_request(
                    "GET", "/api/v1/balance"
                )
                if balance_resp and balance_resp.status == 200:
                    data = await balance_resp.json()
                    self.account.update_balances(data.get("balances", {}))

                # Orders
                orders_resp = await self.network_manager.rest_request(
                    "GET", "/api/v1/orders"
                )
                if orders_resp and orders_resp.status == 200:
                    data = await orders_resp.json()
                    self.account.update_orders(data.get("orders", []))

            except Exception as e:
                self.health.rest_check(False)
                print(f"REST error: {e}")

            await asyncio.sleep(2)

    def run_async_loop(self):
        """Run async event loop in thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def main():
            await asyncio.gather(
                self.start_websocket(),
                self.update_account_state(),
            )

        loop.run_until_complete(main())

    def create_app(self):
        """Create Dash application."""
        app = Dash(__name__, update_title=None)
        app.logger.disabled = True
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        logging.getLogger("dash").setLevel(logging.ERROR)
        logging.getLogger("plotly").setLevel(logging.ERROR)

        app.layout = html.Div([
            html.Div([
                html.H1("Exchange Simulator Dashboard", style={"margin": "0"}),
                html.Div(id="connection-status", style={"fontSize": "14px"}),
            ], style={"padding": "20px", "backgroundColor": "#1e1e1e", "color": "white"}),

            html.Div([
                html.Div([
                    html.H3("Market Data"),
                    html.Div(id="market-info"),
                    html.Div([
                        html.Label("Candlestick Interval: ", style={"marginRight": "10px", "fontWeight": "bold"}),
                        dcc.Dropdown(
                            id="candle-interval-selector",
                            options=[
                                {"label": "1 second", "value": 1},
                                {"label": "15 minutes", "value": 900},
                            ],
                            value=1,
                            clearable=False,
                            style={"width": "200px", "display": "inline-block"},
                        ),
                    ], style={"marginBottom": "10px", "marginTop": "10px"}),
                    dcc.Graph(id="price-chart", config={"displayModeBar": False}),
                    dcc.Graph(id="spread-chart", config={"displayModeBar": False}),
                ], style={"width": "70%", "display": "inline-block", "vertical-align": "top", "padding": "10px"}),

                html.Div([
                    html.H3("Account"),
                    html.Div(id="account-info"),
                    html.H3("Orders", style={"marginTop": "30px"}),
                    html.Div(id="orders-info"),
                ], style={"width": "28%", "display": "inline-block", "vertical-align": "top", "padding": "10px"}),
            ]),

            dcc.Interval(id="update-interval", interval=1000, n_intervals=0),
        ], style={"fontFamily": "Arial, sans-serif", "backgroundColor": "#f5f5f5"})

        @app.callback(
            Output("connection-status", "children"),
            Input("update-interval", "n_intervals"),
        )
        def update_connection_status(n):
            health = self.health.get()

            ws_status = "🟢 Connected" if health["ws_connected"] else "🔴 Disconnected"
            rest_status = "🟢 Healthy" if health["rest_healthy"] else "🔴 Unhealthy"

            return html.Div([
                html.Span(f"WebSocket: {ws_status}", style={"marginRight": "20px"}),
                html.Span(f"REST: {rest_status}", style={"marginRight": "20px"}),
                html.Span(f"Messages: {health['ws_message_count']}"),
            ])

        @app.callback(
            Output("market-info", "children"),
            Input("update-interval", "n_intervals"),
        )
        def update_market_info(n):
            data = self.market_data.get()

            if not data["prices"]:
                return "Waiting for data..."

            current_price = data["prices"][-1]
            symbol = data["symbol"] or "Unknown"

            if len(data["prices"]) > 1:
                price_change = data["prices"][-1] - data["prices"][0]
                price_change_pct = (price_change / data["prices"][0]) * 100
                change_color = "#27ae60" if price_change >= 0 else "#e74c3c"
                change_text = f"({price_change:+.2f}, {price_change_pct:+.2f}%)"
            else:
                change_color = "#7f8c8d"
                change_text = "(--)"

            return html.Div([
                html.Div([
                    html.Span(f"{symbol}: ", style={"fontSize": "20px", "fontWeight": "bold"}),
                    html.Span(f"${current_price:,.2f} ", style={"fontSize": "24px", "fontWeight": "bold", "color": "#2980b9"}),
                    html.Span(change_text, style={"color": change_color, "fontSize": "16px"}),
                ]),
            ])

        @app.callback(
            Output("price-chart", "figure"),
            [Input("update-interval", "n_intervals"),
             Input("candle-interval-selector", "value")],
        )
        def update_price_chart(n, interval_value):
            # Handle interval changes
            if interval_value and interval_value != self.current_interval:
                self.candlestick_aggregator.set_interval(interval_value)
                self.current_interval = interval_value

            # Get exactly 120 most recent candles (or all if less than 120)
            candles = self.candlestick_aggregator.get_candles(max_candles=120)
            data = self.market_data.get()

            if not candles:
                return {"data": [], "layout": go.Layout(title="Price Movement", template="plotly_white")}

            # Extract OHLCV data from candles and convert timestamps to local timezone
            timestamps = []
            for c in candles:
                ts = c["timestamp"]
                # Convert UTC to local timezone if timezone-aware
                if ts.tzinfo is not None:
                    ts = ts.astimezone()
                timestamps.append(ts)
            
            opens = [c["open"] for c in candles]
            highs = [c["high"] for c in candles]
            lows = [c["low"] for c in candles]
            closes = [c["close"] for c in candles]

            # Calculate x-axis range to show exactly 120 candles worth of time
            # Use the current interval to determine the time span
            if len(candles) > 0:
                # Calculate the time span for 120 candles
                time_span_seconds = 120 * self.current_interval
                # Start from the first candle's timestamp (already converted to local)
                xaxis_start = timestamps[0]
                # End at first timestamp + time span (with small padding for better visualization)
                xaxis_end = xaxis_start + timedelta(seconds=time_span_seconds + self.current_interval)
                
                xaxis_range = [xaxis_start, xaxis_end]
            else:
                xaxis_range = None

            return {
                "data": [
                    go.Candlestick(
                        x=timestamps,
                        open=opens,
                        high=highs,
                        low=lows,
                        close=closes,
                        name="Price",
                        increasing_line_color="#27ae60",
                        decreasing_line_color="#e74c3c",
                        increasing_fillcolor="#27ae60",
                        decreasing_fillcolor="#e74c3c",
                    ),
                ],
                "layout": go.Layout(
                    title=f"{data.get('symbol', 'Unknown')} Price - Candlestick Chart",
                    xaxis={
                        "title": "Time",
                        "range": xaxis_range,
                        "fixedrange": True,  # Prevent zoom/pan on x-axis
                    },
                    yaxis={
                        "title": "Price (USD)",
                        # y-axis remains dynamic (auto-scaling)
                    },
                    template="plotly_white",
                    hovermode="x unified",
                    height=350,
                    margin={"l": 50, "r": 20, "t": 40, "b": 40},
                ),
            }

        @app.callback(
            Output("spread-chart", "figure"),
            [Input("update-interval", "n_intervals"),
             Input("candle-interval-selector", "value")],
        )
        def update_spread_chart(n, interval_value):
            data = self.market_data.get(max_points=1000)

            if not data["prices"]:
                return {"data": [], "layout": go.Layout(title="Bid-Ask Spread", template="plotly_white")}

            spreads = [ask - bid for bid, ask in zip(data["bids"], data["asks"])]

            # Convert timestamps to local timezone
            local_timestamps = []
            for ts in data["timestamps"]:
                if ts.tzinfo is not None:
                    ts = ts.astimezone()
                local_timestamps.append(ts)

            # Calculate the same x-axis range as the price chart (120 candles worth of time)
            # Get the candles to determine the exact time window used in the price chart
            candles = self.candlestick_aggregator.get_candles(max_candles=120)
            if len(candles) > 0:
                # Use the same calculation as the price chart
                time_span_seconds = 120 * self.current_interval
                xaxis_start_ts = candles[0]["timestamp"]
                # Convert to local timezone
                if xaxis_start_ts.tzinfo is not None:
                    xaxis_start_ts = xaxis_start_ts.astimezone()
                xaxis_start = xaxis_start_ts
                xaxis_end = xaxis_start + timedelta(seconds=time_span_seconds + self.current_interval)
                xaxis_range = [xaxis_start, xaxis_end]
            elif len(local_timestamps) > 0:
                # Fallback: calculate from tick data if no candles yet
                time_span_seconds = 120 * self.current_interval
                xaxis_end = local_timestamps[-1]
                xaxis_start = xaxis_end - timedelta(seconds=time_span_seconds)
                xaxis_range = [xaxis_start, xaxis_end]
            else:
                xaxis_range = None

            return {
                "data": [
                    go.Scatter(
                        x=local_timestamps,
                        y=spreads,
                        mode="lines",
                        fill="tozeroy",
                        line={"color": "#9b59b6", "width": 2},
                    ),
                ],
                "layout": go.Layout(
                    title="Bid-Ask Spread",
                    xaxis={
                        "title": "Time",
                        "range": xaxis_range,
                        "fixedrange": True,  # Prevent zoom/pan on x-axis, keep in sync with price chart
                    },
                    yaxis={"title": "Spread (USD)"},
                    template="plotly_white",
                    height=250,
                    margin={"l": 50, "r": 20, "t": 40, "b": 40},
                ),
            }

        @app.callback(
            Output("account-info", "children"),
            Input("update-interval", "n_intervals"),
        )
        def update_account_info(n):
            state = self.account.get()

            if not state["balances"]:
                return "Loading..."

            balance_items = [
                html.Div([
                    html.Span(f"{asset}: ", style={"fontWeight": "bold"}),
                    html.Span(f"{balance}"),
                ], style={"padding": "5px"})
                for asset, balance in state["balances"].items()
            ]

            return html.Div(balance_items, style={
                "backgroundColor": "white",
                "padding": "15px",
                "borderRadius": "5px",
                "marginTop": "10px",
            })

        @app.callback(
            Output("orders-info", "children"),
            Input("update-interval", "n_intervals"),
        )
        def update_orders_info(n):
            state = self.account.get()

            if not state["orders"]:
                return html.Div("No open orders", style={
                    "backgroundColor": "white",
                    "padding": "15px",
                    "borderRadius": "5px",
                    "marginTop": "10px",
                })

            order_items = []
            for order in state["orders"][:10]:
                color = "#27ae60" if order["side"] == "BUY" else "#e74c3c"
                order_items.append(
                    html.Div([
                        html.Div(f"{order['side']} {order['quantity']} @ ${order['price']}", style={
                            "fontWeight": "bold",
                            "color": color,
                        }),
                        html.Div(f"Status: {order['status']}", style={"fontSize": "12px", "color": "#7f8c8d"}),
                    ], style={"padding": "8px", "borderBottom": "1px solid #ecf0f1"})
                )

            return html.Div(order_items, style={
                "backgroundColor": "white",
                "padding": "15px",
                "borderRadius": "5px",
                "marginTop": "10px",
                "maxHeight": "400px",
                "overflowY": "auto",
            })

        return app

    def run(self):
        """Start dashboard."""
        self.running = True

        thread = Thread(target=self.run_async_loop, daemon=True)
        thread.start()

        app = self.create_app()

        print("\nDashboard running at http://127.0.0.1:8050")
        print("Press Ctrl+C to stop\n")

        try:
            app.run(debug=False, host="127.0.0.1", port=8050)
        except KeyboardInterrupt:
            print("\nStopping dashboard...")
            self.running = False
            # Close network manager connections
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.network_manager.close())
                loop.close()
            except Exception as e:
                print(f"Error closing network manager: {e}")
