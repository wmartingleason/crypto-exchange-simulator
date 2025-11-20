# Quick Start Guide

## Installation

```bash
git clone <repository>
cd crypto-exchange-simulator
pip install -e ".[dev]"
```

## Basic Usage

### 1. Start the Server

```bash
python -m exchange_simulator.server
```

You should see:
```
============================================================
EXCHANGE SIMULATOR
============================================================
Server: localhost:8765
Symbols: BTC/USD, ETH/USD
Tick Interval: 1.0s
Pricing Model: GBM
  Drift (μ): 0.0
  Volatility (σ): 0.2
Failure Injection: DISABLED
============================================================
REST API: http://localhost:8765/api/v1
WebSocket: ws://localhost:8765/ws
============================================================

Server started
```

### 2. Run the Client Dashboard

In a new terminal:

```bash
python -m client.client
```

You should see:
```
============================================================
Exchange Simulator - Trading Dashboard
============================================================
Symbol: BTC/USD
Server: http://localhost:8765
============================================================

Dashboard running at http://127.0.0.1:8050
Press Ctrl+C to stop
```

Open your browser to http://127.0.0.1:8050 to see the trading dashboard.

### 3. Run Infrastructure Tests

```bash
python -m client.client --scenarios
```

This runs automated testing scenarios:
- Basic trading operations
- Market data streaming
- Rapid order placement/cancellation

## Command Options

### Server

```bash
# Default configuration
python -m exchange_simulator.server

# With custom config file (place config.json in working directory)
python -m exchange_simulator.server
```

### Client

```bash
# Trading dashboard (default)
python -m client.client

# Infrastructure testing scenarios
python -m client.client --scenarios

# Custom symbol
python -m client.client --symbol ETH/USD

# Custom server URL
python -m client.client --base-url http://localhost:9000

# Scenarios with custom URL
python -m client.client --scenarios --base-url http://localhost:9000
```

## Programmatic Usage

### Server

```python
import asyncio
from exchange_simulator.server import ExchangeServer
from exchange_simulator.config import Config

async def main():
    config = Config()
    config.exchange.tick_interval = 0.001  # 1ms updates
    config.failures.enabled = True

    server = ExchangeServer(config)
    await server.start()

    try:
        await asyncio.Future()  # Run forever
    except KeyboardInterrupt:
        await server.stop()

asyncio.run(main())
```

### Client

```python
import asyncio
from client import ExchangeClient

async def main():
    async with ExchangeClient() as client:
        # Get ticker
        ticker = await client.get_ticker("BTC/USD")
        print(f"Price: ${ticker['last_price']}")

        # Place order
        order = await client.place_order(
            symbol="BTC/USD",
            side="BUY",
            order_type="LIMIT",
            quantity="0.5",
            price="49000"
        )
        print(f"Order: {order['order_id']}")

        # Get balance
        balance = await client.get_balance()
        print(f"Balance: {balance}")

asyncio.run(main())
```

## Configuration

Example `config.json`:

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

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=src/exchange_simulator

# Specific test suite
pytest tests/unit/test_rest_api.py -v
```

## Next Steps

- Read [README.md](README.md) for more detailed documentation
- Check [REST_API.md](REST_API.md) for API reference
- Review example configuration in `examples/config.json`
