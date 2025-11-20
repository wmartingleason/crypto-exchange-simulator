"""Market data generator for simulating price movements."""

import asyncio
import math
import random
from decimal import Decimal
from typing import Optional, Dict
from datetime import datetime

from ..models.messages import MarketDataMessage, TradeMessage
from ..models.orders import OrderSide


class PriceModel:
    """Base class for price models."""

    def next_price(self, current: Decimal) -> Decimal:
        """Generate next price.

        Args:
            current: Current price

        Returns:
            Next price
        """
        raise NotImplementedError


class RandomWalkModel(PriceModel):
    """Random walk price model."""

    def __init__(self, volatility: float = 0.001) -> None:
        """Initialize random walk model.

        Args:
            volatility: Price volatility (fraction of price)
        """
        self.volatility = volatility

    def next_price(self, current: Decimal) -> Decimal:
        """Generate next price using random walk."""
        change = float(current) * self.volatility * random.gauss(0, 1)
        new_price = current + Decimal(str(change))
        return max(new_price, Decimal("0.01"))  # Ensure positive price

class GBMPriceModel(PriceModel):
    """
    Geometric Brownian Motion (GBM) price model.

    Formula: S_t = S_{t-1} * exp((mu - 0.5 * sigma^2) * dt + sigma * sqrt(dt) * Z)

    The drift and volatility parameters should be annualized. The dt parameter
    represents the time step in years (e.g., 1.0 for yearly, 1/252 for daily,
    1/(252*24*60*60) for per-second updates with trading days).
    """

    def __init__(
        self,
        drift: float = 0.0,
        volatility: float = 0.1,
        dt: float = 1.0,
        tick_interval_seconds: Optional[float] = None
    ) -> None:
        """Initialize GBM model.

        Args:
            drift (mu): Annualized expected return (e.g., 0.05 for 5% annual growth).
                        Defaults to 0.0 (random walk with no trend).
            volatility (sigma): Annualized standard deviation of returns (e.g., 0.2 for 20%).
            dt (delta t): Time step size in years. If tick_interval_seconds is provided,
                         this will be automatically calculated. Otherwise defaults to 1.0.
            tick_interval_seconds: The actual time between ticks in seconds. If provided,
                                  dt will be calculated as tick_interval_seconds / SECONDS_PER_YEAR.
        """
        self.drift = drift
        self.volatility = volatility

        # If tick_interval_seconds is provided, calculate dt in years
        # Using 252 trading days * 24 hours * 60 minutes * 60 seconds
        if tick_interval_seconds is not None:
            SECONDS_PER_YEAR = 252 * 24 * 60 * 60  # Trading year
            self.dt = tick_interval_seconds / SECONDS_PER_YEAR
            self.tick_interval_seconds = tick_interval_seconds
        else:
            self.dt = dt
            self.tick_interval_seconds = None

    def next_price(self, current: Decimal) -> Decimal:
        """Generate next price using Geometric Brownian Motion."""
        # 1. Calculate the deterministic drift component: (mu - 0.5 * sigma^2) * dt
        drift_component = (self.drift - 0.5 * self.volatility**2) * self.dt

        # 2. Calculate the stochastic (random) component: sigma * sqrt(dt) * Z
        # random.gauss(0, 1) represents Z (Standard Normal Distribution)
        shock = self.volatility * math.sqrt(self.dt) * random.gauss(0, 1)

        # 3. Combine exponents
        exponent = drift_component + shock

        # 4. Calculate the multiplier: e^(drift + shock)
        # We use math.exp for the calculation, then convert to Decimal for currency precision
        multiplier = Decimal(str(math.exp(exponent)))

        # 5. Apply to current price
        new_price = current * multiplier

        return new_price


class TrendModel(PriceModel):
    """Trending price model."""

    def __init__(self, trend: float = 0.0001, volatility: float = 0.001) -> None:
        """Initialize trend model.

        Args:
            trend: Trend direction and strength (positive=up, negative=down)
            volatility: Price volatility
        """
        self.trend = trend
        self.volatility = volatility

    def next_price(self, current: Decimal) -> Decimal:
        """Generate next price with trend."""
        trend_component = float(current) * self.trend
        random_component = float(current) * self.volatility * random.gauss(0, 1)
        new_price = current + Decimal(str(trend_component + random_component))
        return max(new_price, Decimal("0.01"))


class MarketDataGenerator:
    """Generates simulated market data."""

    def __init__(
        self,
        symbol: str,
        initial_price: Decimal,
        tick_interval: float = 0.1,
        price_model: Optional[PriceModel] = None,
    ) -> None:
        """Initialize market data generator.

        Args:
            symbol: Trading symbol
            initial_price: Starting price
            tick_interval: Time between price updates (seconds)
            price_model: Price model to use (defaults to RandomWalk)
        """
        self.symbol = symbol
        self.current_price = initial_price
        self.tick_interval = tick_interval
        self.price_model = price_model or RandomWalkModel()

        self.high_24h = initial_price
        self.low_24h = initial_price
        self.volume_24h = Decimal("0")
        self.last_update = datetime.utcnow()

        self._running = False
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Start generating market data."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._generate_loop())

    async def stop(self) -> None:
        """Stop generating market data."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _generate_loop(self) -> None:
        """Main generation loop."""
        while self._running:
            await asyncio.sleep(self.tick_interval)
            self._update_price()

    def _update_price(self) -> None:
        """Update current price."""
        new_price = self.price_model.next_price(self.current_price)
        self.current_price = new_price

        # Update 24h high/low
        if new_price > self.high_24h:
            self.high_24h = new_price
        if new_price < self.low_24h:
            self.low_24h = new_price

        self.last_update = datetime.utcnow()

    def get_current_price(self) -> Decimal:
        """Get current price.

        Returns:
            Current price
        """
        return self.current_price

    def set_price(self, price: Decimal) -> None:
        """Manually set the current price.

        Args:
            price: New price
        """
        self.current_price = price
        self.last_update = datetime.utcnow()

    def get_market_data_message(self) -> MarketDataMessage:
        """Generate a market data message.

        Returns:
            Market data message
        """
        # Simulate bid/ask spread (0.01% of price)
        spread = self.current_price * Decimal("0.0001")
        bid = self.current_price - spread / 2
        ask = self.current_price + spread / 2

        return MarketDataMessage(
            symbol=self.symbol,
            last_price=self.current_price,
            bid=bid,
            ask=ask,
            volume_24h=self.volume_24h,
            high_24h=self.high_24h,
            low_24h=self.low_24h,
        )

    def generate_trade_message(self, quantity: Optional[Decimal] = None) -> TradeMessage:
        """Generate a simulated trade message.

        Args:
            quantity: Trade quantity (random if not provided)

        Returns:
            Trade message
        """
        if quantity is None:
            quantity = Decimal(str(random.uniform(0.1, 2.0)))

        side = OrderSide.BUY if random.random() > 0.5 else OrderSide.SELL

        # Random small price variation
        price_variation = float(self.current_price) * random.uniform(-0.0001, 0.0001)
        trade_price = self.current_price + Decimal(str(price_variation))

        self.volume_24h += quantity

        return TradeMessage(
            trade_id=f"TRADE_{datetime.utcnow().timestamp()}",
            symbol=self.symbol,
            price=trade_price,
            quantity=quantity,
            side=side,
        )


class MarketDataPublisher:
    """Publishes market data to subscribers."""

    def __init__(self) -> None:
        """Initialize the market data publisher."""
        self.generators: Dict[str, MarketDataGenerator] = {}

    def add_generator(self, generator: MarketDataGenerator) -> None:
        """Add a market data generator.

        Args:
            generator: Generator to add
        """
        self.generators[generator.symbol] = generator

    def get_generator(self, symbol: str) -> Optional[MarketDataGenerator]:
        """Get a generator for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Generator or None if not found
        """
        return self.generators.get(symbol)

    def start_all(self) -> None:
        """Start all generators."""
        for generator in self.generators.values():
            generator.start()

    async def stop_all(self) -> None:
        """Stop all generators."""
        for generator in self.generators.values():
            await generator.stop()
