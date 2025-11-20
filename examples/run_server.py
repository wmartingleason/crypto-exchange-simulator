"""Example script to run the exchange server with configuration."""

import asyncio
import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from exchange_simulator.server import ExchangeServer
from exchange_simulator.config import Config


async def main():
    """Run the exchange server."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Load configuration
    config_path = Path(__file__).parent / "config.json"

    if config_path.exists():
        print(f"Loading configuration from {config_path}")
        config = Config.from_file(str(config_path))
    else:
        print("Using default configuration")
        config = Config()

    # Display configuration summary
    print("\n" + "=" * 60)
    print("EXCHANGE SIMULATOR CONFIGURATION")
    print("=" * 60)
    print(f"Server: {config.server.host}:{config.server.port}")
    print(f"Symbols: {', '.join(config.exchange.symbols)}")
    print(f"Tick Interval: {config.exchange.tick_interval}s ({config.exchange.tick_interval * 1000}ms)")
    print(f"Pricing Model: {config.exchange.pricing_model.model_type.upper()}")
    if config.exchange.pricing_model.model_type == "gbm":
        print(f"  - Drift (μ): {config.exchange.pricing_model.drift} (annualized)")
        print(f"  - Volatility (σ): {config.exchange.pricing_model.volatility} (annualized)")
    print(f"Failure Injection: {'ENABLED' if config.failures.enabled else 'DISABLED'}")

    if config.failures.enabled:
        enabled_modes = [
            mode for mode, cfg in config.failures.modes.items() if cfg.enabled
        ]
        print(f"Active Failure Modes: {', '.join(enabled_modes) if enabled_modes else 'None'}")

    print("=" * 60 + "\n")

    # Create and run server
    server = ExchangeServer(config)

    try:
        await server.run_forever()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
