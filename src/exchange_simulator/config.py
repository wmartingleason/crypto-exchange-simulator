"""Configuration management."""

import json
from typing import Dict, Any, List, Optional
from decimal import Decimal
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    """Server configuration."""

    host: str = Field(default="localhost", description="Server host")
    port: int = Field(default=8765, description="Server port")
    heartbeat_interval: int = Field(default=30, description="Heartbeat interval in seconds")


class PricingModelConfig(BaseModel):
    """Pricing model configuration.

    For GBM model, drift and volatility should be specified as annualized values.
    The model will automatically scale these based on the tick_interval to maintain
    mathematical correctness.

    Example:
        - drift=0.05 means 5% expected annual return
        - volatility=0.20 means 20% annual volatility
        - With tick_interval=1.0 (1 second updates), dt will be 1/(252*24*60*60)
        - With tick_interval=0.001 (1ms updates), dt will be 0.001/(252*24*60*60)
    """

    model_type: str = Field(
        default="gbm",
        description="Pricing model type: 'gbm' (Geometric Brownian Motion) or 'random_walk'"
    )
    drift: float = Field(
        default=0.0,
        description="GBM annualized drift parameter (mu). E.g., 0.05 for 5% annual expected return"
    )
    volatility: float = Field(
        default=0.20,
        description="GBM annualized volatility parameter (sigma). E.g., 0.20 for 20% annual volatility"
    )


class ExchangeConfig(BaseModel):
    """Exchange configuration."""

    symbols: List[str] = Field(default=["BTC/USD"], description="Trading symbols")
    initial_prices: Dict[str, str] = Field(
        default={"BTC/USD": "50000"},
        description="Initial prices for symbols",
    )
    tick_interval: float = Field(
        default=0.001,
        description="Market data tick interval in seconds (supports millisecond precision, e.g., 0.001 for 1ms)"
    )
    default_balance: Dict[str, str] = Field(
        default={"USD": "100000", "BTC": "10"},
        description="Default account balance",
    )
    pricing_model: PricingModelConfig = Field(
        default_factory=PricingModelConfig,
        description="Pricing model configuration",
    )


class FailureMode(BaseModel):
    """Failure mode configuration."""

    enabled: bool = Field(default=True, description="Whether this failure mode is enabled")
    probability: Optional[float] = Field(None, description="Probability for probabilistic failures")
    min_ms: Optional[int] = Field(None, description="Minimum delay in milliseconds")
    max_ms: Optional[int] = Field(None, description="Maximum delay in milliseconds")
    window_size: Optional[int] = Field(None, description="Window size for reordering")
    max_duplicates: Optional[int] = Field(None, description="Maximum number of duplicates")
    max_messages_per_second: Optional[int] = Field(None, description="Throttle rate")
    corruption_level: Optional[float] = Field(None, description="Corruption level")


class LatencyConfig(BaseModel):
    """Latency simulation configuration."""

    mode: str = Field(
        default="typical",
        description="Latency mode: 'stable' or 'typical'",
    )

    @property
    def mu(self) -> float:
        """Get mu parameter for log-normal distribution."""
        if self.mode == "stable":
            return 3.8
        return 5.0

    @property
    def sigma(self) -> float:
        """Get sigma parameter for log-normal distribution."""
        if self.mode == "stable":
            return 0.2
        return 0.3


class FailuresConfig(BaseModel):
    """Failures configuration."""

    enabled: bool = Field(default=False, description="Enable failure injection")
    latency: LatencyConfig = Field(
        default_factory=LatencyConfig,
        description="Latency simulation configuration",
    )
    modes: Dict[str, FailureMode] = Field(
        default={},
        description="Failure modes configuration",
    )


class Config(BaseModel):
    """Main configuration."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    failures: FailuresConfig = Field(default_factory=FailuresConfig)

    @classmethod
    def from_file(cls, path: str) -> "Config":
        """Load configuration from a JSON file.

        Args:
            path: Path to configuration file

        Returns:
            Config instance
        """
        with open(path, "r") as f:
            data = json.load(f)
        return cls.model_validate(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        """Load configuration from a dictionary.

        Args:
            data: Configuration dictionary

        Returns:
            Config instance
        """
        return cls.model_validate(data)

    def to_file(self, path: str) -> None:
        """Save configuration to a JSON file.

        Args:
            path: Path to save configuration
        """
        with open(path, "w") as f:
            json.dump(self.model_dump(), f, indent=2)

    def get_initial_prices_decimal(self) -> Dict[str, Decimal]:
        """Get initial prices as Decimal values.

        Returns:
            Dictionary of symbol to Decimal price
        """
        return {
            symbol: Decimal(price)
            for symbol, price in self.exchange.initial_prices.items()
        }

    def get_default_balance_decimal(self) -> Dict[str, Decimal]:
        """Get default balance as Decimal values.

        Returns:
            Dictionary of currency to Decimal balance
        """
        return {
            currency: Decimal(balance)
            for currency, balance in self.exchange.default_balance.items()
        }
