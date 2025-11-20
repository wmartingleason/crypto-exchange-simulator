"""Exchange simulator client with integrated dashboard."""

import asyncio
import aiohttp
import json
from typing import Optional, Dict, List
from threading import Thread

from .dashboard import TradingDashboard


class ExchangeClient:
    """Client for interacting with exchange simulator."""

    def __init__(self, base_url: str = "http://localhost:8765", session_id: str = "client"):
        self.base_url = base_url
        self.session_id = session_id
        self.headers = {"X-Session-ID": session_id}
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None

    async def __aenter__(self):
        self._http_session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._http_session:
            await self._http_session.close()

    async def connect_ws(self) -> bool:
        """Connect to WebSocket."""
        try:
            self._ws = await self._http_session.ws_connect(f"{self.base_url.replace('http', 'ws')}/ws")
            return True
        except Exception as e:
            print(f"WebSocket connection failed: {e}")
            return False

    async def subscribe(self, channel: str, symbol: str) -> bool:
        """Subscribe to WebSocket channel."""
        if not self._ws or self._ws.closed:
            return False

        msg = {
            "type": "SUBSCRIBE",
            "channel": channel,
            "symbol": symbol,
            "request_id": f"{channel}_{symbol}",
        }
        await self._ws.send_str(json.dumps(msg))
        return True

    async def receive_ws_message(self, timeout: float = 1.0) -> Optional[Dict]:
        """Receive WebSocket message."""
        if not self._ws or self._ws.closed:
            return None

        try:
            msg = await asyncio.wait_for(self._ws.receive(), timeout=timeout)
            if msg.type == aiohttp.WSMsgType.TEXT:
                return json.loads(msg.data)
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            print(f"WebSocket receive error: {e}")
            return None

    async def get_balance(self) -> Optional[Dict[str, str]]:
        """Get account balance via REST."""
        try:
            async with self._http_session.get(
                f"{self.base_url}/api/v1/balance",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["balances"]
        except Exception as e:
            print(f"Get balance failed: {e}")
        return None

    async def get_ticker(self, symbol: str) -> Optional[Dict]:
        """Get ticker data via REST."""
        try:
            async with self._http_session.get(
                f"{self.base_url}/api/v1/ticker?symbol={symbol}"
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            print(f"Get ticker failed: {e}")
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

        try:
            async with self._http_session.post(
                f"{self.base_url}/api/v1/orders",
                json=order_data,
                headers=self.headers
            ) as resp:
                if resp.status == 201:
                    return await resp.json()
                else:
                    data = await resp.json()
                    print(f"Order placement failed: {data.get('error')}")
        except Exception as e:
            print(f"Place order failed: {e}")
        return None

    async def get_orders(self, status: Optional[str] = None) -> List[Dict]:
        """Get orders via REST."""
        url = f"{self.base_url}/api/v1/orders"
        if status:
            url += f"?status={status}"

        try:
            async with self._http_session.get(url, headers=self.headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["orders"]
        except Exception as e:
            print(f"Get orders failed: {e}")
        return []

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order via REST."""
        try:
            async with self._http_session.delete(
                f"{self.base_url}/api/v1/orders/{order_id}",
                headers=self.headers
            ) as resp:
                return resp.status == 200
        except Exception as e:
            print(f"Cancel order failed: {e}")
            return False


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
