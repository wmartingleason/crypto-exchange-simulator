"""Example client demonstrating both REST API and WebSocket usage."""

import asyncio
import aiohttp
import json


async def rest_api_examples(session_id: str):
    """Demonstrate REST API usage.

    Args:
        session_id: Session identifier for requests
    """
    base_url = "http://localhost:8765"
    headers = {"X-Session-ID": session_id}

    async with aiohttp.ClientSession() as session:
        print("\n" + "=" * 60)
        print("REST API EXAMPLES")
        print("=" * 60)

        # Health check
        print("\n1. Health Check")
        async with session.get(f"{base_url}/health") as resp:
            data = await resp.json()
            print(f"   Status: {resp.status}")
            print(f"   Response: {data}")

        # Get symbols
        print("\n2. Get Available Symbols")
        async with session.get(f"{base_url}/api/v1/symbols") as resp:
            data = await resp.json()
            print(f"   Symbols: {data['symbols']}")

        # Get ticker
        print("\n3. Get Ticker Data")
        async with session.get(f"{base_url}/api/v1/ticker?symbol=BTC/USD") as resp:
            data = await resp.json()
            print(f"   Symbol: {data['symbol']}")
            print(f"   Last Price: ${data['last_price']}")
            print(f"   Bid: ${data['bid']}")
            print(f"   Ask: ${data['ask']}")

        # Get balance
        print("\n4. Get Account Balance")
        async with session.get(f"{base_url}/api/v1/balance", headers=headers) as resp:
            data = await resp.json()
            print(f"   Balances: {data['balances']}")

        # Place a limit buy order
        print("\n5. Place Limit Buy Order")
        order_data = {
            "symbol": "BTC/USD",
            "side": "BUY",
            "type": "LIMIT",
            "price": "49000",
            "quantity": "0.5",
        }
        async with session.post(
            f"{base_url}/api/v1/orders", json=order_data, headers=headers
        ) as resp:
            data = await resp.json()
            if resp.status != 201:
                print(f"\n❌ ERROR: {data.get('error', 'Unknown error')}")
                print(f"   Status Code: {resp.status}")
                print(f"   Full Response: {data}")
                return
            print(f"   Order ID: {data['order_id']}")
            print(f"   Status: {data['status']}")
            print(f"   Price: ${data['price']}")
            print(f"   Quantity: {data['quantity']}")
            order_id = data["order_id"]

        # Get all orders
        print("\n6. Get All Orders")
        async with session.get(f"{base_url}/api/v1/orders", headers=headers) as resp:
            data = await resp.json()
            print(f"   Total Orders: {len(data['orders'])}")
            for order in data["orders"]:
                print(
                    f"   - {order['order_id'][:8]}... {order['side']} "
                    f"{order['quantity']} @ ${order['price']} ({order['status']})"
                )

        # Get specific order
        print(f"\n7. Get Order {order_id[:8]}...")
        async with session.get(
            f"{base_url}/api/v1/orders/{order_id}", headers=headers
        ) as resp:
            data = await resp.json()
            print(f"   Symbol: {data['symbol']}")
            print(f"   Side: {data['side']}")
            print(f"   Status: {data['status']}")

        # Cancel order
        print(f"\n8. Cancel Order {order_id[:8]}...")
        async with session.delete(
            f"{base_url}/api/v1/orders/{order_id}", headers=headers
        ) as resp:
            data = await resp.json()
            print(f"   Result: {data['status']}")

        # Get position
        print("\n9. Get Position")
        async with session.get(
            f"{base_url}/api/v1/position?symbol=BTC/USD", headers=headers
        ) as resp:
            data = await resp.json()
            print(f"   Symbol: {data['symbol']}")
            print(f"   Asset: {data['asset']}")
            print(f"   Quantity: {data['quantity']}")


async def websocket_examples(session_id: str):
    """Demonstrate WebSocket usage.

    Args:
        session_id: Session identifier for websocket
    """
    ws_url = "ws://localhost:8765/ws"

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            print("\n" + "=" * 60)
            print("WEBSOCKET EXAMPLES")
            print("=" * 60)

            # Subscribe to market data
            print("\n1. Subscribe to TICKER for BTC/USD")
            subscribe_msg = {
                "type": "SUBSCRIBE",
                "channel": "TICKER",
                "symbol": "BTC/USD",
                "request_id": "SUB1",
            }
            await ws.send_str(json.dumps(subscribe_msg))
            print("   Subscribed - listening for market data...")

            # Receive a few market data messages
            for i in range(3):
                msg = await ws.receive()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data.get("type") == "MARKET_DATA":
                        print(f"   Update {i+1}: Price ${data['last_price']}")

            # Place order via WebSocket
            print("\n2. Place Order via WebSocket")
            order_msg = {
                "type": "PLACE_ORDER",
                "request_id": "ORDER1",
                "symbol": "BTC/USD",
                "side": "BUY",
                "order_type": "LIMIT",
                "price": "48500",
                "quantity": "0.25",
            }
            await ws.send_str(json.dumps(order_msg))

            # Wait for response
            msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("type") == "ORDER_ACK":
                    print(f"   Order Acknowledged: {data['order_id'][:8]}...")
                    print(f"   Status: {data['status']}")
                    ws_order_id = data["order_id"]

                    # Cancel via WebSocket
                    print("\n3. Cancel Order via WebSocket")
                    cancel_msg = {
                        "type": "CANCEL_ORDER",
                        "request_id": "CANCEL1",
                        "order_id": ws_order_id,
                    }
                    await ws.send_str(json.dumps(cancel_msg))

                    # Wait for cancel confirmation
                    msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if data.get("type") == "ORDER_CANCEL":
                            print(f"   Order Cancelled: {data['order_id'][:8]}...")

            print("\n   WebSocket examples complete")


async def hybrid_usage_pattern():
    """Demonstrate typical hybrid REST/WS pattern used by real bots."""
    session_id = "hybrid-bot-session"

    print("\n" + "=" * 60)
    print("HYBRID USAGE PATTERN (Typical Bot Behavior)")
    print("=" * 60)
    print(
        "\nReal trading bots use REST for reliable state queries and commands,\n"
        "while using WebSocket for real-time market data and fast updates."
    )

    base_url = "http://localhost:8765"
    ws_url = "ws://localhost:8765/ws"
    headers = {"X-Session-ID": session_id}

    async with aiohttp.ClientSession() as http_session:
        # Use REST to get initial state
        print("\n1. Use REST to get initial state...")
        async with http_session.get(
            f"{base_url}/api/v1/balance", headers=headers
        ) as resp:
            balance = await resp.json()
            print(f"   Initial Balance: {balance['balances']}")

        async with http_session.get(f"{base_url}/api/v1/ticker?symbol=BTC/USD") as resp:
            ticker = await resp.json()
            print(f"   Current BTC/USD Price: ${ticker['last_price']}")

        # Connect WebSocket for real-time updates
        print("\n2. Connect WebSocket for real-time market data...")
        async with http_session.ws_connect(ws_url) as ws:
            subscribe_msg = {
                "type": "SUBSCRIBE",
                "channel": "TICKER",
                "symbol": "BTC/USD",
                "request_id": "SUB1",
            }
            await ws.send_str(json.dumps(subscribe_msg))
            print("   Subscribed to TICKER feed")

            # Monitor price and place order via REST when condition met
            print("\n3. Monitor price and use REST for trading...")
            for i in range(5):
                msg = await ws.receive()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data.get("type") == "MARKET_DATA":
                        price = float(data["last_price"])
                        print(f"   Market Update: ${price:.2f}")

                        # Example: Place order via REST if price crosses threshold
                        if i == 2:  # Simulate condition being met
                            print("\n4. Condition met - placing order via REST...")
                            order_data = {
                                "symbol": "BTC/USD",
                                "side": "BUY",
                                "type": "LIMIT",
                                "price": str(int(price) - 100),
                                "quantity": "0.1",
                            }
                            async with http_session.post(
                                f"{base_url}/api/v1/orders",
                                json=order_data,
                                headers=headers,
                            ) as resp:
                                order = await resp.json()
                                print(f"   Order placed: {order['order_id'][:8]}...")
                                created_order_id = order["order_id"]

                        # Continue monitoring WebSocket for fills/updates
                        # while using REST for queries
                        if i == 4:
                            print("\n5. Use REST to check final order status...")
                            async with http_session.get(
                                f"{base_url}/api/v1/orders", headers=headers
                            ) as resp:
                                orders = await resp.json()
                                print(f"   Total open orders: {len(orders['orders'])}")

            print("\n   Hybrid pattern demonstration complete")


async def main():
    """Main entry point."""
    print("\n" + "=" * 60)
    print("CRYPTO EXCHANGE SIMULATOR - CLIENT EXAMPLES")
    print("=" * 60)
    print("\nMake sure the hybrid server is running:")
    print("  python examples/run_hybrid_server.py")
    print("\nPress Ctrl+C to stop")

    await asyncio.sleep(1)

    # Run examples
    try:
        await rest_api_examples("rest-demo-session")
        await asyncio.sleep(1)
        await websocket_examples("ws-demo-session")
        await asyncio.sleep(1)
        await hybrid_usage_pattern()

        print("\n" + "=" * 60)
        print("ALL EXAMPLES COMPLETED SUCCESSFULLY")
        print("=" * 60)

    except aiohttp.ClientConnectorError:
        print("\n❌ ERROR: Could not connect to server")
        print("   Make sure the hybrid server is running:")
        print("   python examples/server.py")
    except KeyError as e:
        print(f"\n❌ ERROR: Missing expected field in response: {e}")
        print("   This likely means the server returned an error.")
        print("   Check the server logs for details.")
    except Exception as e:
        print(f"\n❌ ERROR: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
