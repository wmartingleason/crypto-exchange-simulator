## REST API

The exchange simulator provides a complete REST API for reliable state queries and trading operations. WebSocket connectivity is available for real-time market data streams.

### Base URL

```
http://localhost:8765
```

### Authentication

Use the `X-Session-ID` header to identify your session:

```http
X-Session-ID: your-session-id
```

Defaults to `rest-session` if not provided.

### Endpoints

#### Health Check

```http
GET /health
```

**Response:**
```json
{
  "status": "ok",
  "service": "crypto-exchange-simulator"
}
```

#### Get Symbols

```http
GET /api/v1/symbols
```

**Response:**
```json
{
  "symbols": ["BTC/USD", "ETH/USD"]
}
```

#### Get Ticker

```http
GET /api/v1/ticker?symbol=BTC/USD
```

**Response:**
```json
{
  "symbol": "BTC/USD",
  "last_price": "50000.00",
  "bid": "49995.00",
  "ask": "50005.00",
  "high_24h": "51000.00",
  "low_24h": "49000.00",
  "volume_24h": "125.5",
  "timestamp": "2025-01-15T10:30:00.000000"
}
```

#### Place Order

```http
POST /api/v1/orders
Content-Type: application/json
X-Session-ID: your-session-id

{
  "symbol": "BTC/USD",
  "side": "BUY",
  "type": "LIMIT",
  "price": "49000",
  "quantity": "0.5",
  "time_in_force": "GTC"
}
```

**Parameters:**
- `symbol` (required): Trading symbol
- `side` (required): "BUY" or "SELL"
- `type` (required): "LIMIT" or "MARKET"
- `price` (required for LIMIT): Order price
- `quantity` (required): Order quantity
- `time_in_force` (optional): "GTC", "IOC", or "FOK"

**Response (201):**
```json
{
  "order_id": "123e4567-e89b-12d3-a456-426614174000",
  "symbol": "BTC/USD",
  "side": "BUY",
  "type": "LIMIT",
  "status": "OPEN",
  "price": "49000",
  "quantity": "0.5",
  "filled_quantity": "0",
  "created_at": "2025-01-15T10:30:00.000000"
}
```

#### Get Order

```http
GET /api/v1/orders/{order_id}
X-Session-ID: your-session-id
```

**Response (200):**
```json
{
  "order_id": "123e4567-e89b-12d3-a456-426614174000",
  "symbol": "BTC/USD",
  "side": "BUY",
  "type": "LIMIT",
  "status": "OPEN",
  "price": "49000",
  "quantity": "0.5",
  "filled_quantity": "0",
  "created_at": "2025-01-15T10:30:00.000000",
  "updated_at": "2025-01-15T10:30:00.000000"
}
```

#### Get All Orders

```http
GET /api/v1/orders?symbol=BTC/USD&status=OPEN
X-Session-ID: your-session-id
```

**Query Parameters:**
- `symbol` (optional): Filter by symbol
- `status` (optional): Filter by status

**Response (200):**
```json
{
  "orders": [
    {
      "order_id": "123e4567-e89b-12d3-a456-426614174000",
      "symbol": "BTC/USD",
      "side": "BUY",
      "type": "LIMIT",
      "status": "OPEN",
      "price": "49000",
      "quantity": "0.5",
      "filled_quantity": "0",
      "created_at": "2025-01-15T10:30:00.000000"
    }
  ]
}
```

#### Cancel Order

```http
DELETE /api/v1/orders/{order_id}
X-Session-ID: your-session-id
```

**Response (200):**
```json
{
  "order_id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "cancelled"
}
```

#### Get Balance

```http
GET /api/v1/balance
X-Session-ID: your-session-id
```

**Response (200):**
```json
{
  "balances": {
    "USD": "100000.00",
    "BTC": "10.0",
    "ETH": "100.0"
  }
}
```

#### Get Position

```http
GET /api/v1/position?symbol=BTC/USD
X-Session-ID: your-session-id
```

**Response (200):**
```json
{
  "symbol": "BTC/USD",
  "asset": "BTC",
  "quantity": "10.0"
}
```

### Python Client Example

```python
import asyncio
import aiohttp

async def main():
    base_url = "http://localhost:8765"
    headers = {"X-Session-ID": "my-session"}

    async with aiohttp.ClientSession() as session:
        # Get ticker
        async with session.get(f"{base_url}/api/v1/ticker?symbol=BTC/USD") as resp:
            ticker = await resp.json()
            print(f"Price: ${ticker['last_price']}")

        # Place order
        order_data = {
            "symbol": "BTC/USD",
            "side": "BUY",
            "type": "LIMIT",
            "price": "49000",
            "quantity": "0.5"
        }
        async with session.post(
            f"{base_url}/api/v1/orders",
            json=order_data,
            headers=headers
        ) as resp:
            if resp.status == 201:
                order = await resp.json()
                print(f"Order: {order['order_id']}")

        # Get balance
        async with session.get(f"{base_url}/api/v1/balance", headers=headers) as resp:
            balance = await resp.json()
            print(f"Balance: {balance['balances']}")

asyncio.run(main())
```

### WebSocket

Connect to `ws://localhost:8765/ws` for real-time simulated market data. See simulation examples for usage patterns.
