"""Exchange simulator client with integrated dashboard."""

import asyncio
import logging
from threading import Thread
from typing import Optional, Dict, List

import aiohttp

from .dashboard import TradingDashboard
from .network.network_manager import NetworkManager
from .config import ClientConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


class ExchangeClient:
    """Client for interacting with exchange simulator."""

    def __init__(
        self,
        base_url: str = "http://localhost:8765",
        session_id: str = "client",
        config: Optional[ClientConfig] = None,
    ):
        self.base_url = base_url
        self.session_id = session_id
        self.headers = {"X-Session-ID": session_id}
        self.config = config or ClientConfig()
        self.network_manager = NetworkManager(
            base_url=base_url, session_id=session_id, config=self.config
        )
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.network_manager.close()

    async def connect_ws(self) -> bool:
        """Connect to WebSocket."""
        return await self.network_manager.connect_ws()

    async def subscribe(self, channel: str, symbol: str) -> bool:
        """Subscribe to WebSocket channel."""
        msg = {
            "type": "SUBSCRIBE",
            "channel": channel,
            "symbol": symbol,
            "request_id": f"{channel}_{symbol}",
        }
        return await self.network_manager.send_ws_message(msg)

    async def receive_ws_message(self, timeout: float = 1.0) -> Optional[Dict]:
        """Receive WebSocket message."""
        return await self.network_manager.receive_ws_message(timeout=timeout)

    async def get_balance(self) -> Optional[Dict[str, str]]:
        """Get account balance via REST."""
        resp = await self.network_manager.rest_request(
            "GET", "/api/v1/balance", headers=self.headers
        )
        if resp and resp.status == 200:
            data = await resp.json()
            return data.get("balances")
        return None

    async def get_ticker(self, symbol: str) -> Optional[Dict]:
        """Get ticker data via REST."""
        resp = await self.network_manager.rest_request(
            "GET", f"/api/v1/ticker?symbol={symbol}"
        )
        if resp and resp.status == 200:
            return await resp.json()
        return None

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: str,
        price: Optional[str] = None,
    ) -> Optional[Dict]:
        """Place order via REST."""
        order_data = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity,
        }
        if price:
            order_data["price"] = price

        resp = await self.network_manager.rest_request(
            "POST",
            "/api/v1/orders",
            json=order_data,
            headers=self.headers,
        )
        if resp:
            if resp.status == 201:
                return await resp.json()
            else:
                try:
                    data = await resp.json()
                    print(f"Order placement failed: {data.get('error')}")
                except:
                    pass
        return None

    async def get_orders(self, status: Optional[str] = None) -> List[Dict]:
        """Get orders via REST."""
        endpoint = "/api/v1/orders"
        if status:
            endpoint += f"?status={status}"

        resp = await self.network_manager.rest_request(
            "GET", endpoint, headers=self.headers
        )
        if resp and resp.status == 200:
            data = await resp.json()
            return data.get("orders", [])
        return []

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order via REST."""
        resp = await self.network_manager.rest_request(
            "DELETE", f"/api/v1/orders/{order_id}", headers=self.headers
        )
        return resp is not None and resp.status == 200


async def run_scenarios(base_url: str = "http://localhost:8765"):
    """Run infrastructure testing scenarios."""

    async def scenario_basic_trading():
        print("\n" + "=" * 60)
        print("SCENARIO: Basic Trading")
        print("=" * 60)

        async with ExchangeClient(base_url, "scenario_basic") as client:
            balance = await client.get_balance()
            print(f"Initial balance: {balance}")

            ticker = await client.get_ticker("BTC/USD")
            if ticker:
                print(f"Current BTC/USD: ${ticker['last_price']}")

            order = await client.place_order("BTC/USD", "BUY", "LIMIT", "0.1", "49000")
            if order:
                print(f"Order placed: {order['order_id'][:8]}... ({order['status']})")

                orders = await client.get_orders(status="OPEN")
                print(f"Open orders: {len(orders)}")

                if orders:
                    cancelled = await client.cancel_order(order['order_id'])
                    print(f"Order cancelled: {cancelled}")

            final_balance = await client.get_balance()
            print(f"Final balance: {final_balance}")

    async def scenario_market_data_stream():
        print("\n" + "=" * 60)
        print("SCENARIO: Market Data Streaming")
        print("=" * 60)

        async with ExchangeClient(base_url, "scenario_stream") as client:
            if await client.connect_ws():
                print("WebSocket connected")

                if await client.subscribe("TICKER", "BTC/USD"):
                    print("Subscribed to BTC/USD ticker")

                    for i in range(10):
                        msg = await client.receive_ws_message(timeout=2.0)
                        if msg and msg.get("type") == "MARKET_DATA":
                            print(f"#{i+1}: ${msg['last_price']}")

                print("Stream complete")

    async def scenario_rapid_orders():
        print("\n" + "=" * 60)
        print("SCENARIO: Rapid Order Placement")
        print("=" * 60)

        async with ExchangeClient(base_url, "scenario_rapid") as client:
            ticker = await client.get_ticker("BTC/USD")
            if ticker:
                base_price = float(ticker['last_price'])

                orders_placed = []
                for i in range(5):
                    price = str(int(base_price - (i * 100)))
                    order = await client.place_order("BTC/USD", "BUY", "LIMIT", "0.1", price)
                    if order:
                        orders_placed.append(order['order_id'])
                        print(f"Order {i+1}: ${price}")

                print(f"\nPlaced {len(orders_placed)} orders")

                all_orders = await client.get_orders()
                print(f"Total orders: {len(all_orders)}")

                for order_id in orders_placed:
                    await client.cancel_order(order_id)

                print("All orders cancelled")

    try:
        await scenario_basic_trading()
        await asyncio.sleep(1)

        await scenario_market_data_stream()
        await asyncio.sleep(1)

        await scenario_rapid_orders()

        print("\n" + "=" * 60)
        print("All scenarios completed")
        print("=" * 60)

    except aiohttp.ClientConnectorError:
        print("\nERROR: Could not connect to server")
        print("Start server: python -m exchange_simulator.server")
    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}")


def main():
    """Main entry point with integrated dashboard."""
    import argparse

    parser = argparse.ArgumentParser(description="Exchange simulator client")
    parser.add_argument("--scenarios", action="store_true", help="Run testing scenarios instead of dashboard")
    parser.add_argument("--base-url", default="http://localhost:8765", help="Server base URL")
    parser.add_argument("--symbol", default="BTC/USD", help="Trading symbol for dashboard")
    args = parser.parse_args()

    if args.scenarios:
        print("=" * 60)
        print("Exchange Simulator - Infrastructure Testing")
        print("=" * 60)
        print(f"\nServer: {args.base_url}")
        print("\nPress Ctrl+C to stop\n")
        asyncio.run(run_scenarios(args.base_url))
    else:
        print("=" * 60)
        print("Exchange Simulator - Trading Dashboard")
        print("=" * 60)
        print(f"Symbol: {args.symbol}")
        print(f"Server: {args.base_url}")
        print("=" * 60)

        dashboard = TradingDashboard(args.base_url, args.symbol)
        dashboard.run()


if __name__ == "__main__":
    main()
