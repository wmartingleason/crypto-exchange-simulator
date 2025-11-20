"""Trading dashboard for exchange simulator."""

import asyncio
import json
import aiohttp
from datetime import datetime
from collections import deque
from threading import Thread, Lock
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


class TradingDashboard:
    """Trading dashboard with integrated market data and account management."""

    def __init__(self, base_url: str = "http://localhost:8765", symbol: str = "BTC/USD"):
        self.base_url = base_url
        self.ws_url = base_url.replace("http", "ws") + "/ws"
        self.symbol = symbol
        self.session_id = "dashboard"
        self.market_data = MarketDataBuffer()
        self.account = AccountState()
        self.health = ConnectionHealth()
        self.running = False

    async def start_websocket(self):
        while self.running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(self.ws_url) as ws:
                        subscribe_msg = {
                            "type": "SUBSCRIBE",
                            "channel": "TICKER",
                            "symbol": self.symbol,
                            "request_id": "dashboard_sub",
                        }
                        await ws.send_str(json.dumps(subscribe_msg))

                        async for msg in ws:
                            if not self.running:
                                break

                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                self.health.ws_message_received()

                                if data.get("type") == "MARKET_DATA":
                                    timestamp = datetime.fromisoformat(
                                        data["timestamp"].replace("Z", "+00:00")
                                    )
                                    self.market_data.add(
                                        timestamp,
                                        float(data["last_price"]),
                                        float(data["bid"]),
                                        float(data["ask"]),
                                        float(data["volume_24h"]),
                                        data["symbol"],
                                    )
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                self.health.ws_disconnected()
                                break
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                self.health.ws_disconnected()
                                break

            except Exception as e:
                self.health.ws_disconnected()

            if self.running:
                await asyncio.sleep(1)

    async def update_account_state(self):
        """Periodically fetch account state via REST."""
        headers = {"X-Session-ID": self.session_id}

        while self.running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{self.base_url}/health") as resp:
                        self.health.rest_check(resp.status == 200)

                    async with session.get(f"{self.base_url}/api/v1/balance", headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            self.account.update_balances(data["balances"])

                    async with session.get(f"{self.base_url}/api/v1/orders", headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            self.account.update_orders(data["orders"])

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

        app.layout = html.Div([
            html.Div([
                html.H1("Exchange Simulator Dashboard", style={"margin": "0"}),
                html.Div(id="connection-status", style={"fontSize": "14px"}),
            ], style={"padding": "20px", "backgroundColor": "#1e1e1e", "color": "white"}),

            html.Div([
                html.Div([
                    html.H3("Market Data"),
                    html.Div(id="market-info"),
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
            Input("update-interval", "n_intervals"),
        )
        def update_price_chart(n):
            data = self.market_data.get(max_points=1000)

            if not data["prices"]:
                return {"data": [], "layout": go.Layout(title="Price Movement", template="plotly_white")}

            return {
                "data": [
                    go.Scatter(
                        x=data["timestamps"],
                        y=data["prices"],
                        mode="lines",
                        name="Last",
                        line={"color": "#2980b9", "width": 2},
                    ),
                    go.Scatter(
                        x=data["timestamps"],
                        y=data["bids"],
                        mode="lines",
                        name="Bid",
                        line={"color": "#27ae60", "width": 1},
                    ),
                    go.Scatter(
                        x=data["timestamps"],
                        y=data["asks"],
                        mode="lines",
                        name="Ask",
                        line={"color": "#e74c3c", "width": 1},
                    ),
                ],
                "layout": go.Layout(
                    title=f"{data['symbol']} Price",
                    xaxis={"title": "Time"},
                    yaxis={"title": "Price (USD)"},
                    template="plotly_white",
                    hovermode="x unified",
                    height=350,
                    margin={"l": 50, "r": 20, "t": 40, "b": 40},
                ),
            }

        @app.callback(
            Output("spread-chart", "figure"),
            Input("update-interval", "n_intervals"),
        )
        def update_spread_chart(n):
            data = self.market_data.get(max_points=1000)

            if not data["prices"]:
                return {"data": [], "layout": go.Layout(title="Bid-Ask Spread", template="plotly_white")}

            spreads = [ask - bid for bid, ask in zip(data["bids"], data["asks"])]

            return {
                "data": [
                    go.Scatter(
                        x=data["timestamps"],
                        y=spreads,
                        mode="lines",
                        fill="tozeroy",
                        line={"color": "#9b59b6", "width": 2},
                    ),
                ],
                "layout": go.Layout(
                    title="Bid-Ask Spread",
                    xaxis={"title": "Time"},
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
