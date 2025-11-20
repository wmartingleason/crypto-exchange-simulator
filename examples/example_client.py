"""Real-time price visualization client using Plotly Dash."""

import asyncio
import json
import websockets
from datetime import datetime
from collections import deque
from threading import Thread, Lock
import plotly.graph_objs as go
from dash import Dash, dcc, html
from dash.dependencies import Output, Input


class PriceDataBuffer:
    """Thread-safe buffer for storing price data."""

    def __init__(self, maxlen: int = 1000):
        """Initialize the price data buffer.

        Args:
            maxlen: Maximum number of data points to keep
        """
        self.timestamps = deque(maxlen=maxlen)
        self.prices = deque(maxlen=maxlen)
        self.bids = deque(maxlen=maxlen)
        self.asks = deque(maxlen=maxlen)
        self.volumes = deque(maxlen=maxlen)
        self.lock = Lock()
        self.symbol = None
        self.last_update = None

    def add_data(
        self,
        timestamp: datetime,
        price: float,
        bid: float,
        ask: float,
        volume: float,
        symbol: str,
    ) -> None:
        """Add new price data point.

        Args:
            timestamp: Time of the data point
            price: Last traded price
            bid: Best bid price
            ask: Best ask price
            volume: 24h volume
            symbol: Trading symbol
        """
        with self.lock:
            self.timestamps.append(timestamp)
            self.prices.append(price)
            self.bids.append(bid)
            self.asks.append(ask)
            self.volumes.append(volume)
            self.symbol = symbol
            self.last_update = datetime.now()

    def get_data(self, max_points: int = None) -> dict:
        """Get all buffered data in a thread-safe manner.

        Args:
            max_points: Maximum number of points to return (downsamples if needed)

        Returns:
            Dictionary containing all buffered data
        """
        with self.lock:
            timestamps = list(self.timestamps)
            prices = list(self.prices)
            bids = list(self.bids)
            asks = list(self.asks)
            volumes = list(self.volumes)

            # Downsample if we have more points than requested
            if max_points and len(timestamps) > max_points:
                # Calculate stride to get approximately max_points
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


class WebSocketClient:
    """WebSocket client for receiving market data."""

    def __init__(
        self,
        uri: str,
        symbol: str,
        channel: str,
        buffer: PriceDataBuffer,
    ):
        """Initialize the WebSocket client.

        Args:
            uri: WebSocket server URI
            symbol: Trading symbol to subscribe to
            channel: Channel to subscribe to (TICKER, TRADES, etc.)
            buffer: Price data buffer
        """
        self.uri = uri
        self.symbol = symbol
        self.channel = channel
        self.buffer = buffer
        self.running = False

    async def connect_and_subscribe(self) -> None:
        """Connect to WebSocket and subscribe to market data."""
        print(f"Connecting to {self.uri}...")

        async with websockets.connect(self.uri) as websocket:
            print(f"Connected to {self.uri}")

            # Subscribe to market data
            subscribe_msg = {
                "type": "SUBSCRIBE",
                "channel": self.channel,
                "symbol": self.symbol,
                "request_id": "SUB1",
            }
            await websocket.send(json.dumps(subscribe_msg))
            print(f"Subscribed to {self.channel} for {self.symbol}")

            # Listen for messages
            self.running = True
            message_count = 0

            try:
                while self.running:
                    try:
                        response = await asyncio.wait_for(
                            websocket.recv(), timeout=1.0
                        )
                        message_count += 1
                        self._process_message(response, message_count)
                    except asyncio.TimeoutError:
                        # No message received, continue
                        continue
            except websockets.exceptions.ConnectionClosed:
                print("WebSocket connection closed")
            except Exception as e:
                print(f"Error in WebSocket client: {e}")

    def _process_message(self, message_str: str, count: int) -> None:
        """Process incoming WebSocket message.

        Args:
            message_str: JSON message string
            count: Message count for logging
        """
        try:
            message = json.loads(message_str)
            msg_type = message.get("type")

            if msg_type == "MARKET_DATA":
                # Extract price data
                timestamp_str = message.get("timestamp")
                timestamp = datetime.fromisoformat(
                    timestamp_str.replace("Z", "+00:00")
                )

                price = float(message.get("last_price", 0))
                bid = float(message.get("bid", 0))
                ask = float(message.get("ask", 0))
                volume = float(message.get("volume_24h", 0))
                symbol = message.get("symbol", self.symbol)

                # Add to buffer
                self.buffer.add_data(timestamp, price, bid, ask, volume, symbol)

                # Print update every 10 messages
                if count % 10 == 0:
                    print(
                        f"#{count} - Price: ${price:,.2f}, "
                        f"Bid: ${bid:,.2f}, Ask: ${ask:,.2f}"
                    )

        except json.JSONDecodeError:
            print(f"Failed to decode message: {message_str}")
        except Exception as e:
            print(f"Error processing message: {e}")

    def stop(self) -> None:
        """Stop the WebSocket client."""
        self.running = False


def create_dash_app(buffer: PriceDataBuffer) -> Dash:
    """Create Dash application for real-time visualization.

    Args:
        buffer: Price data buffer

    Returns:
        Dash application instance
    """
    app = Dash(__name__, update_title=None)

    app.layout = html.Div(
        [
            html.H1(
                "Real-Time Crypto Exchange Price Monitor",
                style={"textAlign": "center", "color": "#2c3e50"},
            ),
            html.Div(
                id="live-update-text",
                style={"textAlign": "center", "fontSize": "18px", "marginBottom": "20px"},
            ),
            dcc.Graph(id="live-price-graph", animate=False),
            dcc.Graph(id="live-spread-graph", animate=False),
            dcc.Interval(
                id="interval-component",
                interval=1000,  # Update every 1 second
                n_intervals=0,
            ),
        ],
        style={"padding": "20px"},
    )

    @app.callback(
        Output("live-update-text", "children"),
        Input("interval-component", "n_intervals"),
    )
    def update_metrics(n):
        """Update live metrics text."""
        data = buffer.get_data()

        if not data["prices"]:
            return "Waiting for data..."

        current_price = data["prices"][-1]
        symbol = data["symbol"] or "Unknown"
        volume = data["volumes"][-1] if data["volumes"] else 0
        last_update = data["last_update"]

        # Calculate price change
        if len(data["prices"]) > 1:
            price_change = data["prices"][-1] - data["prices"][0]
            price_change_pct = (price_change / data["prices"][0]) * 100
            change_color = "green" if price_change >= 0 else "red"
            change_text = f"({price_change:+.2f}, {price_change_pct:+.2f}%)"
        else:
            change_color = "gray"
            change_text = "(--)"

        update_time = (
            last_update.strftime("%H:%M:%S") if last_update else "Never"
        )

        return html.Div(
            [
                html.Span(
                    f"{symbol}: ",
                    style={"fontWeight": "bold", "fontSize": "24px"},
                ),
                html.Span(
                    f"${current_price:,.2f} ",
                    style={"fontWeight": "bold", "fontSize": "24px", "color": "#2980b9"},
                ),
                html.Span(
                    change_text,
                    style={"color": change_color, "fontSize": "18px"},
                ),
                html.Br(),
                html.Span(
                    f"24h Volume: {volume:,.2f} | Last Update: {update_time}",
                    style={"fontSize": "14px", "color": "#7f8c8d"},
                ),
            ]
        )

    @app.callback(
        Output("live-price-graph", "figure"),
        Input("interval-component", "n_intervals"),
    )
    def update_price_graph(n):
        """Update price graph."""
        # Get downsampled data (max 1000 points for smooth rendering)
        data = buffer.get_data(max_points=1000)

        if not data["prices"]:
            return {
                "data": [],
                "layout": go.Layout(
                    title="Waiting for data...",
                    xaxis={"title": "Time"},
                    yaxis={"title": "Price (USD)"},
                ),
            }

        # Create traces
        traces = [
            go.Scatter(
                x=data["timestamps"],
                y=data["prices"],
                mode="lines",
                name="Last Price",
                line={"color": "#2980b9", "width": 2},
            ),
            go.Scatter(
                x=data["timestamps"],
                y=data["bids"],
                mode="lines",
                name="Bid",
                line={"color": "#27ae60", "width": 1, "dash": "dot"},
            ),
            go.Scatter(
                x=data["timestamps"],
                y=data["asks"],
                mode="lines",
                name="Ask",
                line={"color": "#e74c3c", "width": 1, "dash": "dot"},
            ),
        ]

        layout = go.Layout(
            title=f"{data['symbol'] or 'BTC/USD'} - Price Movement",
            xaxis={
                "title": "Time",
                "showgrid": True,
                "gridcolor": "#ecf0f1",
            },
            yaxis={
                "title": "Price (USD)",
                "showgrid": True,
                "gridcolor": "#ecf0f1",
            },
            hovermode="x unified",
            plot_bgcolor="white",
            paper_bgcolor="white",
            font={"family": "Arial, sans-serif"},
        )

        return {"data": traces, "layout": layout}

    @app.callback(
        Output("live-spread-graph", "figure"),
        Input("interval-component", "n_intervals"),
    )
    def update_spread_graph(n):
        """Update bid-ask spread graph."""
        # Get downsampled data (max 1000 points for smooth rendering)
        data = buffer.get_data(max_points=1000)

        if not data["prices"] or not data["bids"] or not data["asks"]:
            return {
                "data": [],
                "layout": go.Layout(
                    title="Bid-Ask Spread",
                    xaxis={"title": "Time"},
                    yaxis={"title": "Spread (USD)"},
                ),
            }

        # Calculate spread
        spreads = [ask - bid for bid, ask in zip(data["bids"], data["asks"])]

        traces = [
            go.Scatter(
                x=data["timestamps"],
                y=spreads,
                mode="lines",
                name="Spread",
                fill="tozeroy",
                line={"color": "#9b59b6", "width": 2},
            ),
        ]

        layout = go.Layout(
            title="Bid-Ask Spread Over Time",
            xaxis={
                "title": "Time",
                "showgrid": True,
                "gridcolor": "#ecf0f1",
            },
            yaxis={
                "title": "Spread (USD)",
                "showgrid": True,
                "gridcolor": "#ecf0f1",
            },
            hovermode="x unified",
            plot_bgcolor="white",
            paper_bgcolor="white",
            font={"family": "Arial, sans-serif"},
        )

        return {"data": traces, "layout": layout}

    return app


def run_websocket_client(client: WebSocketClient) -> None:
    """Run WebSocket client in asyncio event loop.

    Args:
        client: WebSocket client instance
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(client.connect_and_subscribe())


def main():
    """Main entry point for the real-time visualization client."""
    # Configuration
    WS_URI = "ws://localhost:8765"
    SYMBOL = "BTC/USD"
    CHANNEL = "TICKER"

    print("=" * 60)
    print("Real-Time Crypto Exchange Price Monitor")
    print("=" * 60)
    print(f"Symbol: {SYMBOL}")
    print(f"Channel: {CHANNEL}")
    print(f"Server: {WS_URI}")
    print("=" * 60)

    # Create shared buffer (large enough to hold data for visualization)
    # At 1ms intervals, this holds ~60 seconds of data
    buffer = PriceDataBuffer(maxlen=60000)

    # Create WebSocket client
    ws_client = WebSocketClient(WS_URI, SYMBOL, CHANNEL, buffer)

    # Start WebSocket client in separate thread
    ws_thread = Thread(target=run_websocket_client, args=(ws_client,), daemon=True)
    ws_thread.start()

    # Create and run Dash app
    print("\nStarting Dash visualization server...")
    print("Open http://127.0.0.1:8050/ in your browser to view the live chart")
    print("\nPress Ctrl+C to stop\n")

    app = create_dash_app(buffer)

    try:
        app.run(debug=False, host="127.0.0.1", port=8050)
    except KeyboardInterrupt:
        print("\nStopping client...")
        ws_client.stop()
        print("Client stopped")


if __name__ == "__main__":
    main()
