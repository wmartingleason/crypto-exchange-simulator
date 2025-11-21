"""Message models for WebSocket communication."""

from enum import Enum
from typing import Optional, Any, Dict, List
from decimal import Decimal
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from .orders import OrderSide, OrderType, OrderStatus, TimeInForce


class MessageType(str, Enum):
    """WebSocket message type enumeration."""

    # Client -> Server
    PLACE_ORDER = "PLACE_ORDER"
    CANCEL_ORDER = "CANCEL_ORDER"
    GET_ORDER = "GET_ORDER"
    GET_ORDERS = "GET_ORDERS"
    GET_BALANCE = "GET_BALANCE"
    GET_POSITION = "GET_POSITION"
    SUBSCRIBE = "SUBSCRIBE"
    UNSUBSCRIBE = "UNSUBSCRIBE"
    PING = "PING"

    # Server -> Client
    ORDER_ACK = "ORDER_ACK"
    ORDER_FILL = "ORDER_FILL"
    ORDER_CANCEL = "ORDER_CANCEL"
    ORDER_REJECT = "ORDER_REJECT"
    BALANCE_UPDATE = "BALANCE_UPDATE"
    POSITION_UPDATE = "POSITION_UPDATE"
    MARKET_DATA = "MARKET_DATA"
    ORDERBOOK_UPDATE = "ORDERBOOK_UPDATE"
    TRADE = "TRADE"
    PONG = "PONG"
    ERROR = "ERROR"


class Channel(str, Enum):
    """Subscription channel enumeration."""

    TRADES = "TRADES"
    TICKER = "TICKER"
    ORDERBOOK = "ORDERBOOK"
    ORDERBOOK_L2 = "ORDERBOOK_L2"


class Message(BaseModel):
    """Base message model."""

    type: MessageType = Field(..., description="Message type")
    request_id: Optional[str] = Field(None, description="Request ID for correlation")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Message timestamp")


# Client -> Server Messages


class PlaceOrderMessage(Message):
    """Place order request."""

    type: MessageType = Field(default=MessageType.PLACE_ORDER)
    symbol: str = Field(..., description="Trading symbol")
    side: OrderSide = Field(..., description="Buy or sell")
    order_type: OrderType = Field(..., description="Order type")
    price: Optional[Decimal] = Field(None, description="Limit price")
    quantity: Decimal = Field(..., gt=0, description="Order quantity")
    time_in_force: TimeInForce = Field(default=TimeInForce.GTC, description="Time in force")


class CancelOrderMessage(Message):
    """Cancel order request."""

    type: MessageType = Field(default=MessageType.CANCEL_ORDER)
    order_id: str = Field(..., description="Order ID to cancel")


class GetOrderMessage(Message):
    """Get order status request."""

    type: MessageType = Field(default=MessageType.GET_ORDER)
    order_id: str = Field(..., description="Order ID to query")


class GetOrdersMessage(Message):
    """Get all orders request."""

    type: MessageType = Field(default=MessageType.GET_ORDERS)
    symbol: Optional[str] = Field(None, description="Filter by symbol")
    status: Optional[OrderStatus] = Field(None, description="Filter by status")


class GetBalanceMessage(Message):
    """Get account balance request."""

    type: MessageType = Field(default=MessageType.GET_BALANCE)


class GetPositionMessage(Message):
    """Get position request."""

    type: MessageType = Field(default=MessageType.GET_POSITION)
    symbol: str = Field(..., description="Trading symbol")


class SubscribeMessage(Message):
    """Subscribe to market data channel."""

    type: MessageType = Field(default=MessageType.SUBSCRIBE)
    channel: Channel = Field(..., description="Channel to subscribe to")
    symbol: str = Field(..., description="Trading symbol")


class UnsubscribeMessage(Message):
    """Unsubscribe from market data channel."""

    type: MessageType = Field(default=MessageType.UNSUBSCRIBE)
    channel: Channel = Field(..., description="Channel to unsubscribe from")
    symbol: str = Field(..., description="Trading symbol")


class PingMessage(Message):
    """Ping message for heartbeat."""

    type: MessageType = Field(default=MessageType.PING)


# Server -> Client Messages


class OrderAckMessage(Message):
    """Order acknowledgment."""

    type: MessageType = Field(default=MessageType.ORDER_ACK)
    order_id: str = Field(..., description="Assigned order ID")
    status: OrderStatus = Field(..., description="Order status")
    symbol: str = Field(..., description="Trading symbol")
    side: OrderSide = Field(..., description="Buy or sell")
    order_type: OrderType = Field(..., description="Order type")
    price: Optional[Decimal] = Field(None, description="Order price")
    quantity: Decimal = Field(..., description="Order quantity")


class OrderFillMessage(Message):
    """Order fill notification."""

    type: MessageType = Field(default=MessageType.ORDER_FILL)
    fill_id: str = Field(..., description="Fill ID")
    order_id: str = Field(..., description="Order ID")
    symbol: str = Field(..., description="Trading symbol")
    side: OrderSide = Field(..., description="Buy or sell")
    price: Decimal = Field(..., description="Execution price")
    quantity: Decimal = Field(..., description="Filled quantity")
    filled_quantity: Decimal = Field(..., description="Total filled quantity")
    remaining_quantity: Decimal = Field(..., description="Remaining quantity")
    status: OrderStatus = Field(..., description="Order status after fill")
    is_maker: bool = Field(default=False, description="Maker or taker")


class OrderCancelMessage(Message):
    """Order cancellation confirmation."""

    type: MessageType = Field(default=MessageType.ORDER_CANCEL)
    order_id: str = Field(..., description="Cancelled order ID")
    symbol: str = Field(..., description="Trading symbol")


class OrderRejectMessage(Message):
    """Order rejection notification."""

    type: MessageType = Field(default=MessageType.ORDER_REJECT)
    order_id: Optional[str] = Field(None, description="Order ID if assigned")
    reason: str = Field(..., description="Rejection reason")


class BalanceUpdateMessage(Message):
    """Account balance update."""

    type: MessageType = Field(default=MessageType.BALANCE_UPDATE)
    balances: Dict[str, Decimal] = Field(..., description="Currency balances")


class PositionUpdateMessage(Message):
    """Position update."""

    type: MessageType = Field(default=MessageType.POSITION_UPDATE)
    symbol: str = Field(..., description="Trading symbol")
    quantity: Decimal = Field(..., description="Position quantity")
    average_price: Decimal = Field(..., description="Average entry price")
    unrealized_pnl: Decimal = Field(..., description="Unrealized PnL")
    realized_pnl: Decimal = Field(..., description="Realized PnL")


class MarketDataMessage(Message):
    """Market data update (ticker)."""

    type: MessageType = Field(default=MessageType.MARKET_DATA)
    symbol: str = Field(..., description="Trading symbol")
    last_price: Decimal = Field(..., description="Last trade price")
    bid: Optional[Decimal] = Field(None, description="Best bid")
    ask: Optional[Decimal] = Field(None, description="Best ask")
    volume_24h: Decimal = Field(default=Decimal("0"), description="24h volume")
    high_24h: Optional[Decimal] = Field(None, description="24h high")
    low_24h: Optional[Decimal] = Field(None, description="24h low")
    sequence_id: int = Field(..., description="Sequence ID for gap detection")


class OrderBookLevel(BaseModel):
    """Order book price level."""

    price: Decimal = Field(..., description="Price level")
    quantity: Decimal = Field(..., description="Total quantity at this level")


class OrderBookUpdateMessage(Message):
    """Order book update."""

    type: MessageType = Field(default=MessageType.ORDERBOOK_UPDATE)
    symbol: str = Field(..., description="Trading symbol")
    bids: List[OrderBookLevel] = Field(..., description="Bid levels")
    asks: List[OrderBookLevel] = Field(..., description="Ask levels")
    sequence: int = Field(..., description="Update sequence number")


class TradeMessage(Message):
    """Public trade notification."""

    type: MessageType = Field(default=MessageType.TRADE)
    trade_id: str = Field(..., description="Trade ID")
    symbol: str = Field(..., description="Trading symbol")
    price: Decimal = Field(..., description="Trade price")
    quantity: Decimal = Field(..., description="Trade quantity")
    side: OrderSide = Field(..., description="Taker side")


class PongMessage(Message):
    """Pong response to ping."""

    type: MessageType = Field(default=MessageType.PONG)


class ErrorMessage(Message):
    """Error message."""

    type: MessageType = Field(default=MessageType.ERROR)
    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")
