"""Order book implementation."""

from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import bisect

from ..models.orders import Order, OrderSide, OrderStatus


class PriceLevel:
    """Represents a price level in the order book."""

    def __init__(self, price: Decimal) -> None:
        """Initialize a price level.

        Args:
            price: Price for this level
        """
        self.price = price
        self.orders: List[Order] = []
        self.total_quantity = Decimal("0")

    def add_order(self, order: Order) -> None:
        """Add an order to this price level.

        Args:
            order: Order to add
        """
        self.orders.append(order)
        self.total_quantity += order.remaining_quantity

    def remove_order(self, order: Order) -> bool:
        """Remove an order from this price level.

        Args:
            order: Order to remove

        Returns:
            True if removed, False if not found
        """
        try:
            self.orders.remove(order)
            self.total_quantity = sum(o.remaining_quantity for o in self.orders)
            return True
        except ValueError:
            return False

    def is_empty(self) -> bool:
        """Check if this price level has no orders.

        Returns:
            True if empty
        """
        return len(self.orders) == 0


class OrderBook:
    """Order book for a trading symbol."""

    def __init__(self, symbol: str) -> None:
        """Initialize an order book.

        Args:
            symbol: Trading symbol
        """
        self.symbol = symbol
        self._bids: Dict[Decimal, PriceLevel] = {}  # price -> PriceLevel
        self._asks: Dict[Decimal, PriceLevel] = {}  # price -> PriceLevel
        self._bid_prices: List[Decimal] = []  # Sorted descending
        self._ask_prices: List[Decimal] = []  # Sorted ascending
        self._orders: Dict[str, Order] = {}  # order_id -> Order

    def add_order(self, order: Order) -> None:
        """Add an order to the book.

        Args:
            order: Order to add
        """
        if order.symbol != self.symbol:
            raise ValueError(f"Order symbol {order.symbol} doesn't match book symbol {self.symbol}")

        if order.price is None:
            raise ValueError("Cannot add market order to book")

        self._orders[order.order_id] = order

        if order.side == OrderSide.BUY:
            if order.price not in self._bids:
                self._bids[order.price] = PriceLevel(order.price)
                # Insert in descending order
                bisect.insort(self._bid_prices, order.price)
                self._bid_prices.sort(reverse=True)
            self._bids[order.price].add_order(order)
        else:
            if order.price not in self._asks:
                self._asks[order.price] = PriceLevel(order.price)
                # Insert in ascending order
                bisect.insort(self._ask_prices, order.price)
            self._asks[order.price].add_order(order)

    def remove_order(self, order_id: str) -> Optional[Order]:
        """Remove an order from the book.

        Args:
            order_id: Order ID to remove

        Returns:
            Removed order or None if not found
        """
        order = self._orders.pop(order_id, None)
        if order is None or order.price is None:
            return None

        if order.side == OrderSide.BUY:
            price_level = self._bids.get(order.price)
            if price_level:
                price_level.remove_order(order)
                if price_level.is_empty():
                    del self._bids[order.price]
                    self._bid_prices.remove(order.price)
        else:
            price_level = self._asks.get(order.price)
            if price_level:
                price_level.remove_order(order)
                if price_level.is_empty():
                    del self._asks[order.price]
                    self._ask_prices.remove(order.price)

        return order

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get an order by ID.

        Args:
            order_id: Order ID

        Returns:
            Order or None if not found
        """
        return self._orders.get(order_id)

    def get_best_bid(self) -> Optional[Decimal]:
        """Get the best (highest) bid price.

        Returns:
            Best bid price or None if no bids
        """
        return self._bid_prices[0] if self._bid_prices else None

    def get_best_ask(self) -> Optional[Decimal]:
        """Get the best (lowest) ask price.

        Returns:
            Best ask price or None if no asks
        """
        return self._ask_prices[0] if self._ask_prices else None

    def get_spread(self) -> Optional[Decimal]:
        """Get the bid-ask spread.

        Returns:
            Spread or None if no bid or ask
        """
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()

        if best_bid is not None and best_ask is not None:
            return best_ask - best_bid
        return None

    def get_mid_price(self) -> Optional[Decimal]:
        """Get the mid-market price.

        Returns:
            Mid price or None if no bid or ask
        """
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()

        if best_bid is not None and best_ask is not None:
            return (best_bid + best_ask) / Decimal("2")
        return None

    def get_depth(self, levels: int = 10) -> Tuple[List[Tuple[Decimal, Decimal]], List[Tuple[Decimal, Decimal]]]:
        """Get order book depth.

        Args:
            levels: Number of price levels to return

        Returns:
            Tuple of (bids, asks) where each is a list of (price, quantity) tuples
        """
        bids = [
            (price, self._bids[price].total_quantity)
            for price in self._bid_prices[:levels]
        ]
        asks = [
            (price, self._asks[price].total_quantity)
            for price in self._ask_prices[:levels]
        ]
        return bids, asks

    def get_volume_at_price(self, price: Decimal, side: OrderSide) -> Decimal:
        """Get total volume at a specific price level.

        Args:
            price: Price level
            side: Order side

        Returns:
            Total volume
        """
        if side == OrderSide.BUY:
            level = self._bids.get(price)
        else:
            level = self._asks.get(price)

        return level.total_quantity if level else Decimal("0")

    def get_order_count(self) -> int:
        """Get the total number of orders in the book.

        Returns:
            Number of orders
        """
        return len(self._orders)

    def clear(self) -> None:
        """Clear all orders from the book."""
        self._bids.clear()
        self._asks.clear()
        self._bid_prices.clear()
        self._ask_prices.clear()
        self._orders.clear()
