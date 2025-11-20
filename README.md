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

### Market Data
- Geometric Brownian Motion (GBM) price model (placeholder)
- Random walk models
- Configurable tick intervals (millisecond precision)
- Real-time market data streams

## Quick Start

### Installation

```bash
pip install -e ".[dev]"
```

### Run Server

```bash
python -m exchange_simulator.server
```

The server provides:
- REST API at `http://localhost:8765/api/v1`
- WebSocket at `ws://localhost:8765/ws`

### Run Client with Dashboard

```bash
# Launch trading dashboard (default mode)
python -m client.client

# Run infrastructure testing scenarios
python -m client.client --scenarios

# Custom symbol
python -m client.client --symbol ETH/USD

# Custom server URL
python -m client.client --base-url http://localhost:9000
```

The dashboard automatically integrates:
- Real-time market data visualization
- Account balances and orders
- Connection health monitoring
- WebSocket + REST integration

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Exchange Server (aiohttp)                  │
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
│                          Client                              │
│  ┌──────────────────────┐    ┌──────────────────────────┐  │
│  │   Trading Dashboard  │    │  Infrastructure Testing  │  │
│  │   (Dash + Plotly)    │    │     (Scenarios)          │  │
│  └──────────────────────┘    └──────────────────────────┘  │
│           │                              │                   │
│           └──────────┬───────────────────┘                  │
│                      │                                       │
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
    "modes": {
      "drop_messages": {
        "enabled": true,
        "probability": 0.05
      },
      "delay_messages": {
        "enabled": true,
        "min_ms": 100,
        "max_ms": 2000
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

## Use Cases

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

## Advanced Usage

### Custom Price Models

```python
from exchange_simulator.market_data.generator import PriceModel

class CustomModel(PriceModel):
    def next_price(self, current):
        return current * (1 + self.calculate_trend())
```

### Monitoring

The dashboard provides real-time monitoring of:
- WebSocket connection health
- REST API availability
- Message throughput
- Account state
- Order book depth

### Scenario Testing

The client includes built-in scenarios:
- Basic trading operations
- Market data streaming
- Rapid order placement
- Combined REST/WebSocket usage

Run with: `python -m client.client --scenarios`

## License

MIT
