# Crypto Exchange Simulator

Infrastructure testing platform for crypto exchange systems. Simulates network failures, latency, and market conditions for resilience testing.

## Features

### Exchange Core
- Order matching engine (FIFO, limit/market orders)
- Account and position management
- Real-time order book
- REST API and WebSocket streams

### Failure Injection
Test systems against realistic infrastructure failures:
- Message drops (packet loss)
- Variable latency (network delays)
- Message duplication
- Out-of-order delivery
- Message corruption
- Rate throttling
- REST API rate limiting with escalating penalties
- Network latency simulation with log-normal distribution (stable/typical link modes)

### Market Data
- Geometric Brownian Motion (GBM) price model (placeholder)
- Configurable tick intervals (millisecond precision)
- Real-time market data streams

## Quick Start

### Installation

```bash
pip install -e ".[dev]"
```

### Run Server

```bash
python -m src.exchange_simulator.server
```

The server provides:
- REST API at `http://localhost:8765/api/v1`
- WebSocket at `ws://localhost:8765/ws`

### Run Client with Dashboard

```bash
# Launch trading dashboard (default mode)
python -m src.client.client


```

The dashboard automatically integrates:
- Real-time market data visualization
- Account balances and orders
- Connection health monitoring
- WebSocket + REST integration

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Exchange Server (aiohttp)                 │
│           REST API (/api/v1/*)  |  WebSocket (/ws)          │
└──────────────────────────┬──────────────────────────────────┘
                           │
                ┌──────────┴──────────┐
                │                     │
         ┌──────▼──────┐      ┌──────▼──────┐
         │  REST API   │      │  WebSocket  │
         │   Handler   │      │   Handler   │
         └──────┬──────┘      └──────┬──────┘
                │                     │
                │         ┌───────────▼───────────┐
                │         │   Failure Injector    │
                │         │  (drop, delay, etc)   │
                │         └───────────┬───────────┘
                │                     │
                │         ┌───────────▼───────────┐
                │         │   Message Router      │
                │         └───────────┬───────────┘
                │                     │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │   Exchange Engine   │
                │  ┌────────────────┐ │
                │  │  Order Book    │ │
                │  │  Matching      │ │
                │  │  Accounts      │ │
                │  └────────────────┘ │
                └─────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                          Client                             │
│  ┌──────────────────────┐    ┌──────────────────────────┐   │
│  │   Trading Dashboard  │    │  Infrastructure Testing  │   │
│  │   (Dash + Plotly)    │    │     (Scenarios)          │   │
│  └──────────────────────┘    └──────────────────────────┘   │
│           │                              │                  │
│           └──────────┬───────────────────┘                  │
│                      │                                      │
│           ┌──────────▼──────────┐                           │
│           │   ExchangeClient    │                           │
│           │  REST + WebSocket   │                           │
│           └─────────────────────┘                           │
└─────────────────────────────────────────────────────────────┘
```

## Configuration

Create `config.json` in your working directory:

```json
{
  "server": {
    "host": "localhost",
    "port": 8765
  },
  "exchange": {
    "symbols": ["BTC/USD", "ETH/USD"],
    "tick_interval": 0.001,
    "initial_prices": {
      "BTC/USD": "50000",
      "ETH/USD": "3000"
    },
    "pricing_model": {
      "model_type": "gbm",
      "drift": 0.0,
      "volatility": 0.20
    },
    "default_balance": {
      "USD": "100000",
      "BTC": "10",
      "ETH": "100"
    }
  },
  "failures": {
    "enabled": true,
    "latency": {
      "mode": "typical"
    },
    "modes": {
      "drop_messages": {
        "enabled": true,
        "probability": 0.05
      },
      "delay_messages": {
        "enabled": true,
        "min_ms": 100,
        "max_ms": 2000
      },
      "rate_limit": {
        "enabled": true
      }
    }
  }
}
```

Or use programmatic configuration:

```python
from exchange_simulator.config import Config
from exchange_simulator.server import ExchangeServer

config = Config()
config.failures.enabled = True
config.exchange.tick_interval = 0.001

server = ExchangeServer(config)
await server.start()
```

## REST API

See [REST_API.md](REST_API.md) for complete API documentation.

### Historical Price Data

Use `/api/v1/prices` to backfill ticks whenever WebSocket data is missed:

```
GET /api/v1/prices?symbol=BTC/USD&start=2025-11-21T00:00:00Z&limit=500
```

```json
{
  "symbol": "BTC/USD",
  "prices": [
    {
      "timestamp": "2025-11-21T00:00:00.123456+00:00",
      "price": "50000.12",
      "bid": "49997.62",
      "ask": "50002.62",
      "volume_24h": "12.5"
    }
  ]
}
```

The server keeps a rolling history per symbol and supports optional `start`, `end`,
and `limit` parameters (default limit 500).

### Rate Limiting

The REST API implements rate limiting to simulate real-world exchange behavior. When enabled, the system:

- Enforces baseline request limits (default: 10 requests/second)
- Reduces limits during high-volume periods
- Applies escalating penalties for violations:
  - **First violation**: 10-second wait period
  - **Second violation** (within 60 seconds): 60-second ban
  - **Third violation**: Permanent account ban

Rate-limited requests return HTTP 429 with `Retry-After` header:

```json
{
  "error": "Rate limit exceeded",
  "retry_after": 10,
  "violation_count": 1
}
```

### Latency Simulation

Network latency is simulated using log-normal distribution for packet interarrival times. Latency is applied independently to:
- Incoming packets (before processing)
- Outgoing packets (before sending)

Two latency modes are available:
- **Stable link**: μ=3.8, σ=0.2 (more reliable connection, EV: ~46ms)
- **Typical link**: μ=5.0, σ=0.3 (typical network conditions, EV: ~155ms)

Configure via `failures.latency.mode` in config.json. Latency simulation runs automatically for all WebSocket and REST API traffic.

For production usage, it will be beneficial to gather latency data for individual exchanges and fit models to the data for analyzing trading strategies, since network connection is a significant point of failure in crypto trading.

Quick example:

```python
from client import ExchangeClient

async with ExchangeClient() as client:
    # Get ticker
    ticker = await client.get_ticker("BTC/USD")
    print(f"Price: ${ticker['last_price']}")

    # Place order
    order = await client.place_order("BTC/USD", "BUY", "LIMIT", "0.5", "49000")
    print(f"Order: {order['order_id']}")

    # Get balance
    balance = await client.get_balance()
    print(f"Balance: {balance}")
```

## WebSocket API

```python
async with ExchangeClient() as client:
    await client.connect_ws()
    await client.subscribe("TICKER", "BTC/USD")

    for _ in range(10):
        msg = await client.receive_ws_message()
        if msg and msg.get("type") == "MARKET_DATA":
            print(f"Price: {msg['last_price']}")
```

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=src/exchange_simulator

# Specific test file
pytest tests/unit/test_rest_api.py
```

## Project Structure

```
src/
├── exchange_simulator/
│   ├── engine/
│   │   ├── exchange.py        # Matching engine
│   │   ├── orderbook.py        # Order book
│   │   └── accounts.py         # Account management
│   ├── handlers/
│   │   ├── order.py            # Order operations
│   │   └── subscription.py     # WebSocket subscriptions
│   ├── market_data/
│   │   └── generator.py        # Price models (GBM, random walk)
│   ├── failures/
│   │   └── strategies.py       # Failure injection strategies
│   ├── models/
│   │   ├── messages.py         # Message schemas
│   │   └── orders.py           # Order models
│   ├── rest_api.py             # REST API handlers
│   ├── server.py               # Main server
│   ├── connection_manager.py   # WebSocket connections
│   ├── message_router.py       # Message routing
│   └── config.py               # Configuration
│
└── client/
    ├── __init__.py
    ├── client.py               # Client implementation with scenarios
    └── dashboard.py            # Trading dashboard

tests/
└── unit/                       # Unit tests
```

## Potential Use Cases

### Infrastructure Resilience Testing
Test trading systems against realistic network failures:
- Dropped orders during placement
- Delayed fill confirmations
- Duplicate messages
- Out-of-order delivery

### Algorithm Development
Develop and test trading algorithms with realistic market data and latency.

### Performance Analysis
Measure system performance under various conditions:
- High-frequency order placement
- Network congestion simulation
- Connection scaling

### Market Data Analysis
Test market data processing with configurable tick intervals and pricing models.

### Monitoring

The dashboard provides real-time monitoring of:
- WebSocket connection health
- REST API availability
- Simulated BTC/USD candlesticks
- Account state
- Order book depth

Run with: `python -m client.client --scenarios`

## License

MIT
