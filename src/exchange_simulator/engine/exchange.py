"""Main exchange engine coordinating orderbook, matching, and accounts."""

import uuid
from decimal import Decimal
from typing import List, Optional, Dict
from datetime import datetime

from ..models.orders import Order, OrderSide, OrderType, OrderStatus, Fill, TimeInForce
from .orderbook import OrderBook
from .accounts import AccountManager


class ExchangeEngine:
    """Main exchange engine."""

    def __init__(self, symbols: List[str], account_manager: Optional[AccountManager] = None) -> None:
        """Initialize the exchange engine.

        Args:
            symbols: List of trading symbols to support
            account_manager: Account manager instance (creates default if not provided)
        """
        self.symbols = set(symbols)
        self.orderbooks: Dict[str, OrderBook] = {symbol: OrderBook(symbol) for symbol in symbols}
        self.account_manager = account_manager or AccountManager()
        self._all_orders: Dict[str, Order] = {}  # All orders ever placed
        self._fills: List[Fill] = []
        self._last_prices: Dict[str, Decimal] = {}

    def place_order(
        self,
        session_id: str,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
    ) -> tuple[Order, List[Fill]]:
        """Place a new order.

        Args:
            session_id: Client session ID
            symbol: Trading symbol
            side: Buy or sell
            order_type: Limit or market
            quantity: Order quantity
            price: Limit price (required for limit orders)
            time_in_force: Time in force

        Returns:
            Tuple of (order, list of fills)

        Raises:
            ValueError: If order parameters are invalid
        """
        if symbol not in self.symbols:
            raise ValueError(f"Unknown symbol: {symbol}")

        order_id = str(uuid.uuid4())

        order = Order(
            order_id=order_id,
            session_id=session_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
            time_in_force=time_in_force,
        )

        account = self.account_manager.get_or_create_account(session_id)

        if not self._validate_order_balance(order, account):
            order.reject()
            self._all_orders[order_id] = order
            raise ValueError("Insufficient balance")

        self._all_orders[order_id] = order
        order.status = OrderStatus.OPEN

        fills = self._match_order(order)

        # If order has remaining quantity and is not IOC/FOK, add to book
        if order.remaining_quantity > 0 and order_type == OrderType.LIMIT:
            if time_in_force == TimeInForce.IOC:
                # Cancel remaining
                order.cancel()
            elif time_in_force == TimeInForce.FOK and not order.is_filled:
                # Reject entire order if not completely filled
                order.reject()
                # Reverse any fills (in real system would prevent fills)
                fills = []
            else:
                # Add to order book
                self.orderbooks[symbol].add_order(order)

        return order, fills

    def cancel_order(self, session_id: str, order_id: str) -> Optional[Order]:
        """Cancel an order.

        Args:
            session_id: Client session ID
            order_id: Order ID to cancel

        Returns:
            Cancelled order or None if not found/cannot cancel

        Raises:
            ValueError: If order cannot be cancelled
        """
        order = self._all_orders.get(order_id)
        if order is None:
            raise ValueError("Order not found")

        if order.session_id != session_id:
            raise ValueError("Order does not belong to this session")

        if order.status not in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED):
            raise ValueError(f"Cannot cancel order with status {order.status}")

        if order.price is not None:
            self.orderbooks[order.symbol].remove_order(order_id)

        order.cancel()
        return order

    def get_order(self, session_id: str, order_id: str) -> Optional[Order]:
        """Get an order.

        Args:
            session_id: Client session ID
            order_id: Order ID

        Returns:
            Order or None if not found
        """
        order = self._all_orders.get(order_id)
        if order and order.session_id == session_id:
            return order
        return None

    def get_orders(
        self,
        session_id: str,
        symbol: Optional[str] = None,
        status: Optional[OrderStatus] = None,
    ) -> List[Order]:
        """Get all orders for a session.

        Args:
            session_id: Client session ID
            symbol: Optional symbol filter
            status: Optional status filter

        Returns:
            List of orders
        """
        orders = [o for o in self._all_orders.values() if o.session_id == session_id]

        if symbol:
            orders = [o for o in orders if o.symbol == symbol]

        if status:
            orders = [o for o in orders if o.status == status]

        return orders

    def get_orderbook(self, symbol: str) -> Optional[OrderBook]:
        """Get the order book for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            OrderBook or None if symbol not found
        """
        return self.orderbooks.get(symbol)

    def get_last_price(self, symbol: str) -> Optional[Decimal]:
        """Get the last trade price for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Last price or None if no trades
        """
        return self._last_prices.get(symbol)

    def set_last_price(self, symbol: str, price: Decimal) -> None:
        """Set the last trade price (for external price updates).

        Args:
            symbol: Trading symbol
            price: Price to set
        """
        self._last_prices[symbol] = price

    def _validate_order_balance(self, order: Order, account) -> bool:
        """Validate that account has sufficient balance for the order.

        Args:
            order: Order to validate
            account: Account to check

        Returns:
            True if balance is sufficient
        """
        # Simplified validation - just check USD balance
        # In reality, would need to check specific currencies based on symbol
        if order.side == OrderSide.BUY and order.price is not None:
            required = order.price * order.quantity
            return account.has_sufficient_balance("USD", required)

        # For sell orders, would check asset balance
        return True

    def _match_order(self, order: Order) -> List[Fill]:
        """Match an order against the order book.

        Args:
            order: Order to match

        Returns:
            List of fills
        """
        fills: List[Fill] = []
        orderbook = self.orderbooks[order.symbol]

        if order.side == OrderSide.BUY:
            # Match against asks
            while order.remaining_quantity > 0:
                best_ask = orderbook.get_best_ask()
                if best_ask is None:
                    break

                # Check if price is acceptable
                if order.order_type == OrderType.LIMIT and order.price is not None:
                    if best_ask > order.price:
                        break

                # Get orders at best ask
                ask_level = orderbook._asks.get(best_ask)
                if not ask_level or ask_level.is_empty():
                    break

                # Match against first order in level (FIFO)
                maker_order = ask_level.orders[0]
                fill = self._execute_fill(order, maker_order, best_ask)
                if fill:
                    fills.append(fill)

                # Remove maker order if filled
                if maker_order.is_filled:
                    orderbook.remove_order(maker_order.order_id)
        else:
            # Match against bids
            while order.remaining_quantity > 0:
                best_bid = orderbook.get_best_bid()
                if best_bid is None:
                    break

                # Check if price is acceptable
                if order.order_type == OrderType.LIMIT and order.price is not None:
                    if best_bid < order.price:
                        break

                # Get orders at best bid
                bid_level = orderbook._bids.get(best_bid)
                if not bid_level or bid_level.is_empty():
                    break

                # Match against first order in level (FIFO)
                maker_order = bid_level.orders[0]
                fill = self._execute_fill(order, maker_order, best_bid)
                if fill:
                    fills.append(fill)

                # Remove maker order if filled
                if maker_order.is_filled:
                    orderbook.remove_order(maker_order.order_id)

        return fills

    def _execute_fill(self, taker_order: Order, maker_order: Order, price: Decimal) -> Optional[Fill]:
        """Execute a fill between two orders.

        Args:
            taker_order: Taker (incoming) order
            maker_order: Maker (resting) order
            price: Execution price

        Returns:
            Fill object or None if cannot execute
        """
        # Calculate fill quantity
        fill_qty = min(taker_order.remaining_quantity, maker_order.remaining_quantity)
        if fill_qty <= 0:
            return None

        # Update orders
        taker_order.fill(fill_qty)
        maker_order.fill(fill_qty)

        # Update last price
        self._last_prices[taker_order.symbol] = price

        # Create fill for taker
        fill = Fill(
            fill_id=str(uuid.uuid4()),
            order_id=taker_order.order_id,
            session_id=taker_order.session_id,
            symbol=taker_order.symbol,
            side=taker_order.side,
            price=price,
            quantity=fill_qty,
            is_maker=False,
        )

        self._fills.append(fill)

        # Update account positions
        taker_account = self.account_manager.get_account(taker_order.session_id)
        if taker_account:
            taker_account.update_position_on_fill(fill, price)

        maker_fill = Fill(
            fill_id=str(uuid.uuid4()),
            order_id=maker_order.order_id,
            session_id=maker_order.session_id,
            symbol=maker_order.symbol,
            side=maker_order.side,
            price=price,
            quantity=fill_qty,
            is_maker=True,
        )

        self._fills.append(maker_fill)

        maker_account = self.account_manager.get_account(maker_order.session_id)
        if maker_account:
            maker_account.update_position_on_fill(maker_fill, price)

        return fill

    def get_fills(self, session_id: Optional[str] = None) -> List[Fill]:
        """Get fills, optionally filtered by session.

        Args:
            session_id: Optional session filter

        Returns:
            List of fills
        """
        if session_id:
            return [f for f in self._fills if f.session_id == session_id]
        return self._fills.copy()
