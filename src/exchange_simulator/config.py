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


class ExchangeConfig(BaseModel):
    """Exchange configuration."""

    symbols: List[str] = Field(default=["BTC/USD"], description="Trading symbols")
    initial_prices: Dict[str, str] = Field(
        default={"BTC/USD": "50000"},
        description="Initial prices for symbols",
    )
    tick_interval: float = Field(default=0.1, description="Market data tick interval")
    default_balance: Dict[str, str] = Field(
        default={"USD": "100000", "BTC": "10"},
        description="Default account balance",
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


class FailuresConfig(BaseModel):
    """Failures configuration."""

    enabled: bool = Field(default=False, description="Enable failure injection")
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
