# Crypto Exchange Simulator

A WebSocket-based crypto exchange simulator designed to simulate network-related trading issues such as disconnections, message drops, phantom fills, and other trading scenarios.

## Features

### Core Exchange Functionality
- **Full Order Lifecycle**: Place, cancel, and query orders
- **Matching Engine**: FIFO matching with limit and market orders
- **Account Management**: Balance tracking and position management
- **Order Book**: Real-time order book with depth and best bid/ask
- **Fill Notifications**: Immediate notification of order fills

### Network Failure Injection
Test your trading systems against various network issues:
- **Message Drops**: Random message loss (configurable probability)
- **Message Delays**: Variable latency (configurable range)
- **Message Duplication**: Simulate duplicate messages
- **Message Reordering**: Out-of-order message delivery
- **Message Corruption**: Corrupted message content
- **Throttling**: Rate limiting

### Market Data
- **Price Simulation**: Random walk and trend-following models
- **Real-time Updates**: Configurable tick intervals
- **Market Data Channels**: Subscribe to trades, ticker, and order book updates

## Quick Start

### 1. Installation

```bash
# Install the package with development dependencies
pip install -e ".[dev]"
```

### 2. Run the Server

```bash
# With default configuration
python examples/run_server.py

# Or with custom config
python examples/run_server.py
```

### 3. Connect a Client

```bash
# In a separate terminal
python examples/simple_client.py
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     WebSocket Server                         │
│                    (asyncio + websockets)                    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   Connection Manager                         │
│  • Tracks client connections & sessions                     │
│  • Manages subscriptions                                    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Message Pipeline                          │
│   Inbound:  Client ──▶ [Failure Layer] ──▶ Router ──▶ Handler │
│   Outbound: Client ◀── [Failure Layer] ◀── Handler           │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Message Handlers                          │
│  • OrderHandler      (place, cancel, query)                 │
│  • SubscriptionHandler (market data subscriptions)          │
│  • HeartbeatHandler  (ping/pong)                           │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     Exchange Engine                          │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ OrderBook  │  │AccountManager│  │MatchEngine   │       │
│  └────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

## Configuration

Create a `config.json` file (see `examples/config.json`):

```json
{
  "server": {
    "host": "localhost",
    "port": 8765
  },
  "exchange": {
    "symbols": ["BTC/USD", "ETH/USD"],
    "initial_prices": {
      "BTC/USD": "50000",
      "ETH/USD": "3000"
    },
    "default_balance": {
      "USD": "100000",
      "BTC": "10"
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

## WebSocket API

### Place Order
```json
{
  "type": "PLACE_ORDER",
  "symbol": "BTC/USD",
  "side": "BUY",
  "order_type": "LIMIT",
  "price": "50000",
  "quantity": "1.5"
}
```

### Cancel Order
```json
{
  "type": "CANCEL_ORDER",
  "order_id": "order-uuid"
}
```

### Subscribe to Market Data
```json
{
  "type": "SUBSCRIBE",
  "channel": "TRADES",
  "symbol": "BTC/USD"
}
```

For complete API documentation, see [USAGE.md](USAGE.md).

## Testing

### Run Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/exchange_simulator --cov-report=html

# Run specific test file
pytest tests/unit/test_orders.py
```

### Test Coverage

The project includes comprehensive tests for:
- ✅ Order models and lifecycle
- ✅ Message models and serialization
- ✅ Connection management
- ✅ Message routing
- ✅ Failure injection strategies
- ✅ Exchange engine and matching
- ✅ Order book operations
- ✅ Account management

## Project Structure

```
crypto-exchange-simulator/
├── src/exchange_simulator/
│   ├── models/              # Data models
│   │   ├── messages.py      # WebSocket message schemas
│   │   └── orders.py        # Order and position models
│   ├── handlers/            # Message handlers
│   │   ├── order.py         # Order operations
│   │   ├── subscription.py  # Subscriptions
│   │   └── heartbeat.py     # Ping/pong
│   ├── engine/              # Exchange engine
│   │   ├── exchange.py      # Main engine
│   │   ├── orderbook.py     # Order book
│   │   └── accounts.py      # Account management
│   ├── market_data/         # Market data
│   │   └── generator.py     # Price generators
│   ├── failures/            # Failure injection
│   │   └── strategies.py    # Failure strategies
│   ├── connection_manager.py
│   ├── message_router.py
│   ├── failure_injector.py
│   ├── config.py
│   └── server.py            # WebSocket server
├── tests/
│   └── unit/                # Unit tests
├── examples/
│   ├── config.json          # Example configuration
│   ├── run_server.py        # Server runner
│   └── simple_client.py     # Example client
├── pyproject.toml
├── README.md
└── USAGE.md
```

## Use Cases

### 1. Test Trading Algorithms
Verify your trading algorithm handles network issues gracefully:
- Message drops during order placement
- Delayed fill confirmations
- Out-of-order messages

### 2. Test Reconnection Logic
Simulate connection failures and test reconnection:
- WebSocket disconnections
- Message queue recovery
- State synchronization

### 3. Test Order State Management
Verify correct order state tracking:
- Phantom fills
- Duplicate fill notifications
- Cancelled order confirmations

### 4. Load Testing
Test system performance:
- High-frequency order placement
- Message throttling
- Connection scaling

## Additional Features

### Custom Price Models

```python
from exchange_simulator.market_data.generator import PriceModel

class TrendingModel(PriceModel):
    def next_price(self, current):
        # Implement custom price logic
        return current * (1 + trend)
```

### Programmatic Configuration

```python
from exchange_simulator.config import Config
from exchange_simulator.server import ExchangeServer

config = Config()
config.failures.enabled = True
config.server.port = 9000

server = ExchangeServer(config)
await server.start()
```

### Monitoring

```python
# Get failure statistics
stats = server.failure_injector.get_statistics()
print(f"Dropped: {stats['inbound']['DropMessageStrategy_0']['dropped_count']}")
print(f"Delayed: {stats['outbound']['DelayMessageStrategy_0']['delayed_count']}")
```

## License

MIT

## Documentation

- [USAGE.md](USAGE.md) - Detailed usage guide
- [examples/](examples/) - Example configurations and clients
