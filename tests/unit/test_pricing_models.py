"""Tests for pricing models."""

import pytest
import math
from decimal import Decimal
from unittest.mock import patch

from src.exchange_simulator.market_data.generator import (
    GBMPriceModel,
    RandomWalkModel,
    PriceModel,
)


class TestPriceModel:
    """Test cases for PriceModel base class."""

    def test_base_class_not_implemented(self) -> None:
        """Test that base class raises NotImplementedError."""
        model = PriceModel()
        with pytest.raises(NotImplementedError):
            model.next_price(Decimal("100"))


class TestGBMPriceModel:
    """Test cases for GBMPriceModel."""

    def test_initialization_default_parameters(self) -> None:
        """Test GBM model initialization with default parameters."""
        model = GBMPriceModel()
        assert model.drift == 0.0
        assert model.volatility == 0.1
        assert model.dt == 1.0
        assert model.tick_interval_seconds is None

    def test_initialization_custom_parameters(self) -> None:
        """Test GBM model initialization with custom parameters."""
        model = GBMPriceModel(drift=0.05, volatility=0.2, dt=0.5)
        assert model.drift == 0.05
        assert model.volatility == 0.2
        assert model.dt == 0.5
        assert model.tick_interval_seconds is None

    def test_initialization_with_tick_interval(self) -> None:
        """Test GBM model initialization with tick_interval_seconds."""
        tick_interval = 1.0  # 1 second
        model = GBMPriceModel(drift=0.05, volatility=0.2, tick_interval_seconds=tick_interval)
        assert model.drift == 0.05
        assert model.volatility == 0.2
        assert model.tick_interval_seconds == 1.0

        # dt should be calculated as tick_interval / SECONDS_PER_YEAR
        SECONDS_PER_YEAR = 252 * 24 * 60 * 60
        expected_dt = tick_interval / SECONDS_PER_YEAR
        assert abs(model.dt - expected_dt) < 1e-10

    def test_initialization_with_millisecond_tick_interval(self) -> None:
        """Test GBM model initialization with millisecond tick interval."""
        tick_interval = 0.001  # 1 millisecond
        model = GBMPriceModel(drift=0.05, volatility=0.2, tick_interval_seconds=tick_interval)

        SECONDS_PER_YEAR = 252 * 24 * 60 * 60
        expected_dt = tick_interval / SECONDS_PER_YEAR
        assert abs(model.dt - expected_dt) < 1e-15

    def test_next_price_returns_decimal(self) -> None:
        """Test that next_price returns a Decimal."""
        model = GBMPriceModel(drift=0.0, volatility=0.1, dt=1.0)
        current_price = Decimal("100.0")
        next_price = model.next_price(current_price)
        assert isinstance(next_price, Decimal)

    def test_next_price_positive(self) -> None:
        """Test that next_price always returns a positive value."""
        model = GBMPriceModel(drift=0.0, volatility=0.1, dt=1.0)
        current_price = Decimal("100.0")

        # Run multiple times to ensure it's always positive
        for _ in range(100):
            next_price = model.next_price(current_price)
            assert next_price > Decimal("0")

    @patch('random.gauss')
    def test_next_price_zero_volatility(self, mock_gauss) -> None:
        """Test next_price with zero volatility (deterministic drift only)."""
        mock_gauss.return_value = 0.0
        model = GBMPriceModel(drift=0.1, volatility=0.0, dt=1.0)
        current_price = Decimal("100.0")

        # With zero volatility and Z=0, price should increase by drift
        # Formula: S_t = S_{t-1} * exp(0.1 * 1.0) = S_{t-1} * exp(0.1)
        expected_multiplier = math.exp(0.1)
        next_price = model.next_price(current_price)
        expected_price = current_price * Decimal(str(expected_multiplier))

        # Allow small floating point difference
        assert abs(next_price - expected_price) < Decimal("0.01")

    @patch('random.gauss')
    def test_next_price_zero_drift(self, mock_gauss) -> None:
        """Test next_price with zero drift (pure random walk)."""
        # Mock random shock
        mock_gauss.return_value = 1.0
        model = GBMPriceModel(drift=0.0, volatility=0.2, dt=1.0)
        current_price = Decimal("100.0")

        # With zero drift and Z=1.0:
        # Formula: S_t = S_{t-1} * exp(-0.5 * 0.2^2 * 1.0 + 0.2 * sqrt(1.0) * 1.0)
        #              = S_{t-1} * exp(-0.02 + 0.2)
        #              = S_{t-1} * exp(0.18)
        expected_multiplier = math.exp(-0.5 * 0.2**2 + 0.2 * 1.0)
        next_price = model.next_price(current_price)
        expected_price = current_price * Decimal(str(expected_multiplier))

        assert abs(next_price - expected_price) < Decimal("0.01")

    @patch('random.gauss')
    def test_next_price_formula_verification(self, mock_gauss) -> None:
        """Test that next_price follows the GBM formula correctly."""
        # Set specific parameters
        drift = 0.05
        volatility = 0.2
        dt = 0.5
        z_value = 1.5
        mock_gauss.return_value = z_value

        model = GBMPriceModel(drift=drift, volatility=volatility, dt=dt)
        current_price = Decimal("100.0")

        # Calculate expected next price using GBM formula
        # S_t = S_{t-1} * exp((mu - 0.5 * sigma^2) * dt + sigma * sqrt(dt) * Z)
        drift_component = (drift - 0.5 * volatility**2) * dt
        shock_component = volatility * math.sqrt(dt) * z_value
        exponent = drift_component + shock_component
        expected_multiplier = math.exp(exponent)
        expected_price = current_price * Decimal(str(expected_multiplier))

        next_price = model.next_price(current_price)

        # Should match within small tolerance
        assert abs(next_price - expected_price) < Decimal("0.01")

    def test_next_price_different_dt_values(self) -> None:
        """Test that dt parameter affects price changes appropriately."""
        current_price = Decimal("100.0")

        # Smaller dt should generally lead to smaller changes
        model_small_dt = GBMPriceModel(drift=0.1, volatility=0.2, dt=0.01)
        model_large_dt = GBMPriceModel(drift=0.1, volatility=0.2, dt=1.0)

        # Calculate average absolute change over multiple runs
        small_dt_changes = []
        large_dt_changes = []

        for _ in range(100):
            small_change = abs(model_small_dt.next_price(current_price) - current_price)
            large_change = abs(model_large_dt.next_price(current_price) - current_price)
            small_dt_changes.append(float(small_change))
            large_dt_changes.append(float(large_change))

        avg_small = sum(small_dt_changes) / len(small_dt_changes)
        avg_large = sum(large_dt_changes) / len(large_dt_changes)

        # Larger dt should lead to larger average changes
        assert avg_large > avg_small

    def test_next_price_volatility_effect(self) -> None:
        """Test that higher volatility leads to more variable prices."""
        current_price = Decimal("100.0")

        model_low_vol = GBMPriceModel(drift=0.0, volatility=0.05, dt=1.0)
        model_high_vol = GBMPriceModel(drift=0.0, volatility=0.5, dt=1.0)

        # Calculate variance of price changes
        low_vol_prices = [float(model_low_vol.next_price(current_price)) for _ in range(100)]
        high_vol_prices = [float(model_high_vol.next_price(current_price)) for _ in range(100)]

        import statistics
        low_vol_variance = statistics.variance(low_vol_prices)
        high_vol_variance = statistics.variance(high_vol_prices)

        # Higher volatility should lead to higher variance
        assert high_vol_variance > low_vol_variance

    def test_next_price_drift_effect(self) -> None:
        """Test that positive drift leads to upward trend."""
        current_price = Decimal("100.0")

        model_positive_drift = GBMPriceModel(drift=0.5, volatility=0.1, dt=1.0)
        model_negative_drift = GBMPriceModel(drift=-0.5, volatility=0.1, dt=1.0)

        # Run simulation
        positive_prices = [float(model_positive_drift.next_price(current_price)) for _ in range(100)]
        negative_prices = [float(model_negative_drift.next_price(current_price)) for _ in range(100)]

        avg_positive = sum(positive_prices) / len(positive_prices)
        avg_negative = sum(negative_prices) / len(negative_prices)

        # Positive drift should lead to higher average price
        assert avg_positive > float(current_price)
        # Negative drift should lead to lower average price
        assert avg_negative < float(current_price)

    @patch('random.gauss')
    def test_next_price_reproducibility_with_mocked_random(self, mock_gauss) -> None:
        """Test that same random values produce same prices."""
        mock_gauss.return_value = 0.5

        model = GBMPriceModel(drift=0.05, volatility=0.2, dt=1.0)
        current_price = Decimal("100.0")

        price1 = model.next_price(current_price)
        price2 = model.next_price(current_price)

        # Same inputs should produce same outputs
        assert price1 == price2

    def test_next_price_sequence(self) -> None:
        """Test generating a sequence of prices."""
        model = GBMPriceModel(drift=0.05, volatility=0.1, dt=1.0)
        current_price = Decimal("100.0")

        prices = [current_price]
        for _ in range(10):
            current_price = model.next_price(current_price)
            prices.append(current_price)

        # Should have 11 prices (initial + 10 steps)
        assert len(prices) == 11
        # All prices should be positive
        assert all(p > Decimal("0") for p in prices)
        # Prices should vary (not all the same)
        assert len(set(prices)) > 1

    def test_realistic_1_second_updates(self) -> None:
        """Test that 1-second updates with realistic annualized parameters produce reasonable prices."""
        # Realistic parameters: 10% annual drift, 30% annual volatility
        model = GBMPriceModel(drift=0.10, volatility=0.30, tick_interval_seconds=1.0)
        current_price = Decimal("50000.0")  # BTC price

        # Simulate 60 seconds of updates
        prices = [float(current_price)]
        for _ in range(60):
            current_price = model.next_price(current_price)
            prices.append(float(current_price))

        # All prices should be positive
        assert all(p > 0 for p in prices)

        # Over 60 seconds with these parameters, we shouldn't see crazy changes
        # Max change should be reasonable (not 10x or 0.1x in just 60 seconds)
        assert max(prices) / min(prices) < 1.01  # Less than 1% change is reasonable for 60 seconds

    def test_realistic_millisecond_updates(self) -> None:
        """Test that millisecond updates with realistic parameters work correctly."""
        # High volatility but very small time steps
        model = GBMPriceModel(drift=0.10, volatility=0.50, tick_interval_seconds=0.001)
        current_price = Decimal("50000.0")

        # Simulate 1000 milliseconds (1 second) of updates
        prices = [float(current_price)]
        for _ in range(1000):
            current_price = model.next_price(current_price)
            prices.append(float(current_price))

        # All prices should be positive
        assert all(p > 0 for p in prices)

        # Even with 50% annual volatility, over 1 second changes should be tiny
        assert max(prices) / min(prices) < 1.005  # Less than 0.5% change in 1 second


class TestRandomWalkModel:
    """Test cases for RandomWalkModel (for backward compatibility)."""

    def test_initialization_default_volatility(self) -> None:
        """Test RandomWalkModel initialization with default volatility."""
        model = RandomWalkModel()
        assert model.volatility == 0.001

    def test_initialization_custom_volatility(self) -> None:
        """Test RandomWalkModel initialization with custom volatility."""
        model = RandomWalkModel(volatility=0.01)
        assert model.volatility == 0.01

    def test_next_price_returns_decimal(self) -> None:
        """Test that next_price returns a Decimal."""
        model = RandomWalkModel(volatility=0.01)
        current_price = Decimal("100.0")
        next_price = model.next_price(current_price)
        assert isinstance(next_price, Decimal)

    def test_next_price_minimum_value(self) -> None:
        """Test that next_price enforces minimum value of 0.01."""
        model = RandomWalkModel(volatility=0.01)
        # Even with very low price, should not go below 0.01
        current_price = Decimal("0.001")
        next_price = model.next_price(current_price)
        assert next_price >= Decimal("0.01")
