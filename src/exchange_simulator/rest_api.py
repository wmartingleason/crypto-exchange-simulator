"""REST API handlers for the exchange simulator."""

import logging
from typing import Dict, Any, Optional
from aiohttp import web
from decimal import Decimal
import json

from .engine.exchange import ExchangeEngine
from .engine.accounts import AccountManager
from .market_data.generator import MarketDataPublisher
from .models.orders import OrderSide, OrderType, OrderStatus, TimeInForce
from .models.messages import PlaceOrderMessage, CancelOrderMessage
from .failures.strategies import RateLimitStrategy, FailureContext, LatencySimulationStrategy

logger = logging.getLogger(__name__)


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


class RateLimiter:
    """Rate limiter middleware for REST API requests."""

    def __init__(self, rate_limit_strategy: Optional[RateLimitStrategy] = None) -> None:
        self.rate_limit_strategy = rate_limit_strategy

    async def check_rate_limit(self, session_id: str, request_path: str = "") -> None:
        if not self.rate_limit_strategy:
            return

        context = FailureContext(
            session_id=session_id,
            message_type="REST_REQUEST",
            direction="inbound",
            metadata={"path": request_path},
        )

        result = await self.rate_limit_strategy.apply("", context)

        if result is None:
            error_msg = context.metadata.get("rate_limit_error", "Rate limit exceeded")
            retry_after = context.metadata.get("retry_after")
            violation_count = self.rate_limit_strategy.get_violation_count(session_id)

            response_data = {
                "error": error_msg,
                "violation_count": violation_count,
            }
            if retry_after is not None:
                response_data["retry_after"] = retry_after

            raise web.HTTPTooManyRequests(
                text=json.dumps(response_data),
                headers={"Retry-After": str(retry_after)} if retry_after is not None else None,
                content_type="application/json",
            )


class RestAPIHandler:
    """REST API request handlers."""

    def __init__(
        self,
        exchange_engine: ExchangeEngine,
        account_manager: AccountManager,
        market_data_publisher: MarketDataPublisher,
        rate_limiter: Optional[RateLimiter] = None,
        latency_strategy: Optional[LatencySimulationStrategy] = None,
    ):
        self.exchange_engine = exchange_engine
        self.account_manager = account_manager
        self.market_data_publisher = market_data_publisher
        self.rate_limiter = rate_limiter
        self.latency_strategy = latency_strategy

    async def _check_rate_limit(self, request: web.Request) -> None:
        if self.rate_limiter:
            session_id = request.headers.get("X-Session-ID", "rest-session")
            await self.rate_limiter.check_rate_limit(session_id, request.path)

    async def _apply_inbound_latency(self) -> None:
        if self.latency_strategy:
            context = FailureContext(
                session_id="rest",
                message_type="REST_REQUEST",
                direction="inbound",
            )
            await self.latency_strategy.apply("", context)

    async def _apply_outbound_latency(self) -> None:
        if self.latency_strategy:
            context = FailureContext(
                session_id="rest",
                message_type="REST_RESPONSE",
                direction="outbound",
            )
            await self.latency_strategy.apply("", context)

    async def health_check(self, request: web.Request) -> web.Response:
        """Health check endpoint.

        GET /health
        """
        return web.json_response({"status": "ok", "service": "crypto-exchange-simulator"})

    async def get_symbols(self, request: web.Request) -> web.Response:
        """Get available trading symbols.

        GET /api/v1/symbols
        """
        await self._check_rate_limit(request)
        await self._apply_inbound_latency()
        symbols = list(self.exchange_engine.symbols)
        await self._apply_outbound_latency()
        return web.json_response({"symbols": symbols})

    async def get_ticker(self, request: web.Request) -> web.Response:
        """Get ticker data for a symbol.

        GET /api/v1/ticker?symbol=BTC/USD
        """
        await self._check_rate_limit(request)
        await self._apply_inbound_latency()
        symbol = request.query.get("symbol")
        if not symbol:
            await self._apply_outbound_latency()
            return web.json_response(
                {"error": "symbol parameter required"}, status=400
            )

        generator = self.market_data_publisher.get_generator(symbol)
        if not generator:
            await self._apply_outbound_latency()
            return web.json_response(
                {"error": f"Symbol {symbol} not found"}, status=404
            )

        market_data = generator.get_market_data_message()
        await self._apply_outbound_latency()
        return web.json_response(
            {
                "symbol": market_data.symbol,
                "last_price": str(market_data.last_price),
                "bid": str(market_data.bid),
                "ask": str(market_data.ask),
                "high_24h": str(market_data.high_24h),
                "low_24h": str(market_data.low_24h),
                "volume_24h": str(market_data.volume_24h),
                "timestamp": market_data.timestamp.isoformat(),
            }
        )

    async def place_order(self, request: web.Request) -> web.Response:
        """Place a new order.

        POST /api/v1/orders
        Body: {
            "symbol": "BTC/USD",
            "side": "BUY" | "SELL",
            "type": "LIMIT" | "MARKET",
            "price": "50000.00",  // Required for LIMIT orders
            "quantity": "0.5",
            "time_in_force": "GTC" | "IOC" | "FOK"  // Optional, defaults to GTC
        }
        """
        await self._check_rate_limit(request)
        await self._apply_inbound_latency()

        try:
            data = await request.json()
        except json.JSONDecodeError:
            await self._apply_outbound_latency()
            return web.json_response({"error": "Invalid JSON"}, status=400)

        # Extract session ID from headers or generate one
        session_id = request.headers.get("X-Session-ID", "rest-session")

        # Validate required fields
        required_fields = ["symbol", "side", "type", "quantity"]
        missing = [f for f in required_fields if f not in data]
        if missing:
            await self._apply_outbound_latency()
            return web.json_response(
                {"error": f"Missing required fields: {', '.join(missing)}"}, status=400
            )

        try:
            # Parse order parameters
            symbol = data["symbol"]
            side = OrderSide(data["side"])
            order_type = OrderType(data["type"])
            quantity = Decimal(data["quantity"])
            price = Decimal(data["price"]) if "price" in data else None
            time_in_force = TimeInForce(data.get("time_in_force", "GTC"))

            # Validate price for LIMIT orders
            if order_type == OrderType.LIMIT and price is None:
                await self._apply_outbound_latency()
                return web.json_response(
                    {"error": "price required for LIMIT orders"}, status=400
                )

            # Place order through engine (returns tuple of order and fills)
            order, fills = self.exchange_engine.place_order(
                session_id=session_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                price=price,
                quantity=quantity,
                time_in_force=time_in_force,
            )

            await self._apply_outbound_latency()
            return web.json_response(
                {
                    "order_id": order.order_id,
                    "symbol": order.symbol,
                    "side": order.side.value,
                    "type": order.order_type.value,
                    "status": order.status.value,
                    "price": str(order.price) if order.price else None,
                    "quantity": str(order.quantity),
                    "filled_quantity": str(order.filled_quantity),
                    "created_at": order.created_at.isoformat(),
                },
                status=201,
            )

        except ValueError as e:
            await self._apply_outbound_latency()
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:
            logger.error(f"Error placing order: {e}", exc_info=True)
            await self._apply_outbound_latency()
            return web.json_response({"error": f"Internal server error: {str(e)}"}, status=500)

    async def cancel_order(self, request: web.Request) -> web.Response:
        """Cancel an existing order.

        DELETE /api/v1/orders/{order_id}
        """
        await self._check_rate_limit(request)
        await self._apply_inbound_latency()
        order_id = request.match_info.get("order_id")
        if not order_id:
            await self._apply_outbound_latency()
            return web.json_response({"error": "order_id required"}, status=400)

        session_id = request.headers.get("X-Session-ID", "rest-session")

        try:
            success = self.exchange_engine.cancel_order(session_id, order_id)
            await self._apply_outbound_latency()
            if success:
                return web.json_response(
                    {"order_id": order_id, "status": "cancelled"}
                )
            else:
                return web.json_response(
                    {"error": "Order not found or cannot be cancelled"}, status=404
                )
        except ValueError as e:
            await self._apply_outbound_latency()
            return web.json_response({"error": str(e)}, status=404)
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            await self._apply_outbound_latency()
            return web.json_response({"error": "Internal server error"}, status=500)

    async def get_order(self, request: web.Request) -> web.Response:
        """Get order details.

        GET /api/v1/orders/{order_id}
        """
        await self._check_rate_limit(request)
        await self._apply_inbound_latency()
        order_id = request.match_info.get("order_id")
        if not order_id:
            await self._apply_outbound_latency()
            return web.json_response({"error": "order_id required"}, status=400)

        session_id = request.headers.get("X-Session-ID", "rest-session")

        order = self.exchange_engine.get_order(session_id, order_id)
        if not order:
            await self._apply_outbound_latency()
            return web.json_response({"error": "Order not found"}, status=404)

        await self._apply_outbound_latency()
        return web.json_response(
            {
                "order_id": order.order_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "type": order.order_type.value,
                "status": order.status.value,
                "price": str(order.price) if order.price else None,
                "quantity": str(order.quantity),
                "filled_quantity": str(order.filled_quantity),
                "created_at": order.created_at.isoformat(),
                "updated_at": order.updated_at.isoformat(),
            }
        )

    async def get_orders(self, request: web.Request) -> web.Response:
        """Get all orders for the session.

        GET /api/v1/orders?symbol=BTC/USD&status=OPEN
        """
        await self._check_rate_limit(request)
        await self._apply_inbound_latency()
        session_id = request.headers.get("X-Session-ID", "rest-session")
        symbol = request.query.get("symbol")
        status = request.query.get("status")

        order_status = OrderStatus(status) if status else None
        orders = self.exchange_engine.get_orders(session_id, symbol, order_status)

        await self._apply_outbound_latency()
        return web.json_response(
            {
                "orders": [
                    {
                        "order_id": order.order_id,
                        "symbol": order.symbol,
                        "side": order.side.value,
                        "type": order.order_type.value,
                        "status": order.status.value,
                        "price": str(order.price) if order.price else None,
                        "quantity": str(order.quantity),
                        "filled_quantity": str(order.filled_quantity),
                        "created_at": order.created_at.isoformat(),
                    }
                    for order in orders
                ]
            }
        )

    async def get_balance(self, request: web.Request) -> web.Response:
        """Get account balance.

        GET /api/v1/balance
        """
        await self._check_rate_limit(request)
        await self._apply_inbound_latency()
        session_id = request.headers.get("X-Session-ID", "rest-session")

        account = self.account_manager.get_or_create_account(session_id)

        await self._apply_outbound_latency()
        return web.json_response(
            {
                "balances": {
                    asset: str(balance) for asset, balance in account.balances.items()
                }
            }
        )

    async def get_position(self, request: web.Request) -> web.Response:
        """Get position for a symbol.

        GET /api/v1/position?symbol=BTC/USD
        """
        await self._check_rate_limit(request)
        await self._apply_inbound_latency()
        session_id = request.headers.get("X-Session-ID", "rest-session")
        symbol = request.query.get("symbol")

        if not symbol:
            await self._apply_outbound_latency()
            return web.json_response({"error": "symbol parameter required"}, status=400)

        account = self.account_manager.get_or_create_account(session_id)

        # Extract base asset from symbol (e.g., BTC from BTC/USD)
        base_asset = symbol.split("/")[0]
        position = account.balances.get(base_asset, Decimal("0"))

        await self._apply_outbound_latency()
        return web.json_response(
            {"symbol": symbol, "asset": base_asset, "quantity": str(position)}
        )


def create_rest_routes(handler: RestAPIHandler) -> list:
    """Create REST API routes.

    Args:
        handler: REST API handler instance

    Returns:
        List of aiohttp routes
    """
    return [
        web.get("/health", handler.health_check),
        web.get("/api/v1/symbols", handler.get_symbols),
        web.get("/api/v1/ticker", handler.get_ticker),
        web.post("/api/v1/orders", handler.place_order),
        web.delete("/api/v1/orders/{order_id}", handler.cancel_order),
        web.get("/api/v1/orders/{order_id}", handler.get_order),
        web.get("/api/v1/orders", handler.get_orders),
        web.get("/api/v1/balance", handler.get_balance),
        web.get("/api/v1/position", handler.get_position),
    ]
