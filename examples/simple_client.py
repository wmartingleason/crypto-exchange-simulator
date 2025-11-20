"""Simple WebSocket client example for the exchange simulator."""

import asyncio
import json
import websockets
from datetime import datetime


async def main():
    """Run a simple client that places orders."""
    uri = "ws://localhost:8765"

    async with websockets.connect(uri) as websocket:
        print(f"Connected to {uri}")

        # Send a ping
        ping_msg = {
            "type": "PING",
            "request_id": "PING1",
        }
        await websocket.send(json.dumps(ping_msg))
        print(f"Sent: {ping_msg}")

        response = await websocket.recv()
        print(f"Received: {response}\n")

        # Subscribe to trades
        subscribe_msg = {
            "type": "SUBSCRIBE",
            "channel": "TRADES",
            "symbol": "BTC/USD",
            "request_id": "SUB1",
        }
        await websocket.send(json.dumps(subscribe_msg))
        print(f"Sent: {subscribe_msg}\n")

        # Place a limit buy order
        order_msg = {
            "type": "PLACE_ORDER",
            "request_id": "ORDER1",
            "symbol": "BTC/USD",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": "50000",
            "quantity": "0.5",
        }
        await websocket.send(json.dumps(order_msg))
        print(f"Sent: {order_msg}")

        response = await websocket.recv()
        print(f"Received: {response}")

        response_data = json.loads(response)
        order_id = response_data.get("order_id")
        print(f"Order placed with ID: {order_id}\n")

        # Wait a moment
        await asyncio.sleep(2)

        # Place a matching sell order
        sell_msg = {
            "type": "PLACE_ORDER",
            "request_id": "ORDER2",
            "symbol": "BTC/USD",
            "side": "SELL",
            "order_type": "LIMIT",
            "price": "50000",
            "quantity": "0.5",
        }
        await websocket.send(json.dumps(sell_msg))
        print(f"Sent: {sell_msg}")

        response = await websocket.recv()
        print(f"Received: {response}\n")

        # Cancel the first order if still open
        if order_id:
            cancel_msg = {
                "type": "CANCEL_ORDER",
                "request_id": "CANCEL1",
                "order_id": order_id,
            }
            await websocket.send(json.dumps(cancel_msg))
            print(f"Sent: {cancel_msg}")

            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                print(f"Received: {response}\n")
            except asyncio.TimeoutError:
                print("No response received (order might be filled or message dropped)\n")

        print("Client session complete")


if __name__ == "__main__":
    asyncio.run(main())
