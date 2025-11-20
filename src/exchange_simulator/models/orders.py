"""Order models for the exchange simulator."""

from enum import Enum
from typing import Optional
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator


class OrderSide(str, Enum):
    """Order side enumeration."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Order type enumeration."""

    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(str, Enum):
    """Order status enumeration."""

    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class TimeInForce(str, Enum):
    """Time in force enumeration."""

    GTC = "GTC"  # Good til cancelled
    IOC = "IOC"  # Immediate or cancel
    FOK = "FOK"  # Fill or kill


class Order(BaseModel):
    """Represents an order in the exchange."""

    order_id: str = Field(..., description="Unique order identifier")
    session_id: str = Field(..., description="Client session ID")
    symbol: str = Field(..., description="Trading symbol (e.g., BTC/USD)")
    side: OrderSide = Field(..., description="Buy or sell")
    order_type: OrderType = Field(..., description="Limit or market")
    price: Optional[Decimal] = Field(None, description="Limit price (required for LIMIT orders)")
    quantity: Decimal = Field(..., gt=0, description="Order quantity")
    filled_quantity: Decimal = Field(default=Decimal("0"), ge=0, description="Filled quantity")
    status: OrderStatus = Field(default=OrderStatus.PENDING, description="Order status")
    time_in_force: TimeInForce = Field(default=TimeInForce.GTC, description="Time in force")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update timestamp")

    @model_validator(mode='after')
    def validate_order(self) -> 'Order':
        """Validate order fields."""
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("Price is required for LIMIT orders")
        if self.price is not None and self.price <= 0:
            raise ValueError("Price must be positive")
        return self

    @property
    def remaining_quantity(self) -> Decimal:
        """Calculate remaining unfilled quantity."""
        return self.quantity - self.filled_quantity

    @property
    def is_filled(self) -> bool:
        """Check if order is completely filled."""
        return self.filled_quantity >= self.quantity

    def fill(self, quantity: Decimal) -> None:
        """Fill the order partially or completely.

        Args:
            quantity: Amount to fill

        Raises:
            ValueError: If fill quantity exceeds remaining quantity
        """
        if quantity <= 0:
            raise ValueError("Fill quantity must be positive")
        if quantity > self.remaining_quantity:
            raise ValueError("Fill quantity exceeds remaining quantity")

        self.filled_quantity += quantity
        self.updated_at = datetime.utcnow()

        if self.is_filled:
            self.status = OrderStatus.FILLED
        elif self.filled_quantity > 0:
            self.status = OrderStatus.PARTIALLY_FILLED

    def cancel(self) -> None:
        """Cancel the order."""
        if self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            raise ValueError(f"Cannot cancel order with status {self.status}")
        self.status = OrderStatus.CANCELLED
        self.updated_at = datetime.utcnow()

    def reject(self) -> None:
        """Reject the order."""
        self.status = OrderStatus.REJECTED
        self.updated_at = datetime.utcnow()


class Fill(BaseModel):
    """Represents a fill (trade execution)."""

    fill_id: str = Field(..., description="Unique fill identifier")
    order_id: str = Field(..., description="Order that was filled")
    session_id: str = Field(..., description="Client session ID")
    symbol: str = Field(..., description="Trading symbol")
    side: OrderSide = Field(..., description="Buy or sell")
    price: Decimal = Field(..., gt=0, description="Execution price")
    quantity: Decimal = Field(..., gt=0, description="Filled quantity")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Execution timestamp")
    is_maker: bool = Field(default=False, description="True if maker, False if taker")


class Position(BaseModel):
    """Represents a trading position."""

    symbol: str = Field(..., description="Trading symbol")
    quantity: Decimal = Field(default=Decimal("0"), description="Position size (positive=long, negative=short)")
    average_price: Decimal = Field(default=Decimal("0"), ge=0, description="Average entry price")
    realized_pnl: Decimal = Field(default=Decimal("0"), description="Realized profit/loss")
    unrealized_pnl: Decimal = Field(default=Decimal("0"), description="Unrealized profit/loss")

    def update_on_fill(self, fill: Fill) -> None:
        """Update position based on a fill.

        Args:
            fill: The fill to process
        """
        fill_qty = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity

        # Calculate realized PnL if reducing position
        if (self.quantity > 0 and fill_qty < 0) or (self.quantity < 0 and fill_qty > 0):
            closing_qty = min(abs(fill_qty), abs(self.quantity))
            self.realized_pnl += closing_qty * (fill.price - self.average_price) * (1 if self.quantity > 0 else -1)

        # Update position
        old_qty = self.quantity
        new_qty = self.quantity + fill_qty

        # Update average price if increasing position or flipping
        if (old_qty >= 0 and new_qty > old_qty) or (old_qty <= 0 and new_qty < old_qty) or (old_qty * new_qty < 0):
            if new_qty != 0:
                if old_qty * new_qty <= 0:  # Flipping or starting new position
                    self.average_price = fill.price
                else:  # Adding to existing position
                    total_value = abs(old_qty) * self.average_price + abs(fill_qty) * fill.price
                    self.average_price = total_value / abs(new_qty)

        self.quantity = new_qty

    def calculate_unrealized_pnl(self, current_price: Decimal) -> Decimal:
        """Calculate unrealized PnL at current price.

        Args:
            current_price: Current market price

        Returns:
            Unrealized profit/loss
        """
        if self.quantity == 0:
            self.unrealized_pnl = Decimal("0")
        else:
            self.unrealized_pnl = self.quantity * (current_price - self.average_price)
        return self.unrealized_pnl
