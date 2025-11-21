"""Tests for REST API endpoints."""

import pytest
from decimal import Decimal
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from src.exchange_simulator.rest_api import RestAPIHandler, create_rest_routes
from src.exchange_simulator.engine.exchange import ExchangeEngine
from src.exchange_simulator.engine.accounts import AccountManager
from src.exchange_simulator.market_data.generator import (
    MarketDataPublisher,
    MarketDataGenerator,
    RandomWalkModel,
)


class TestRestAPI(AioHTTPTestCase):
    """Test REST API endpoints."""

    async def get_application(self):
        """Create test application."""
        # Initialize components
        default_balance = {"USD": Decimal("100000"), "BTC": Decimal("10")}
        self.account_manager = AccountManager(default_balance)
        self.exchange_engine = ExchangeEngine(
            symbols=["BTC/USD"], account_manager=self.account_manager
        )
        self.market_data_publisher = MarketDataPublisher()

        # Add market data generator
        generator = MarketDataGenerator(
            symbol="BTC/USD",
            initial_price=Decimal("50000"),
            tick_interval=1.0,
            price_model=RandomWalkModel(),
        )
        self.market_data_publisher.add_generator(generator)
        self.exchange_engine.set_last_price("BTC/USD", Decimal("50000"))

        # Create REST API handler
        self.rest_handler = RestAPIHandler(
            self.exchange_engine, self.account_manager, self.market_data_publisher
        )

        # Create app and add routes
        app = web.Application()
        routes = create_rest_routes(self.rest_handler)
        app.router.add_routes(routes)
        return app

    @unittest_run_loop
    async def test_health_check(self):
        """Test health check endpoint."""
        resp = await self.client.request("GET", "/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "crypto-exchange-simulator"

    @unittest_run_loop
    async def test_get_symbols(self):
        """Test get symbols endpoint."""
        resp = await self.client.request("GET", "/api/v1/symbols")
        assert resp.status == 200
        data = await resp.json()
        assert "symbols" in data
        assert "BTC/USD" in data["symbols"]

    @unittest_run_loop
    async def test_get_ticker(self):
        """Test get ticker endpoint."""
        resp = await self.client.request("GET", "/api/v1/ticker?symbol=BTC/USD")
        assert resp.status == 200
        data = await resp.json()
        assert data["symbol"] == "BTC/USD"
        assert "last_price" in data
        assert "bid" in data
        assert "ask" in data
        assert "high_24h" in data
        assert "low_24h" in data
        assert "volume_24h" in data
        assert "timestamp" in data

    @unittest_run_loop
    async def test_get_ticker_missing_symbol(self):
        """Test get ticker without symbol parameter."""
        resp = await self.client.request("GET", "/api/v1/ticker")
        assert resp.status == 400
        data = await resp.json()
        assert "error" in data

    @unittest_run_loop
    async def test_get_ticker_invalid_symbol(self):
        """Test get ticker with invalid symbol."""
        resp = await self.client.request("GET", "/api/v1/ticker?symbol=INVALID")
        assert resp.status == 404
        data = await resp.json()
        assert "error" in data

    @unittest_run_loop
    async def test_place_limit_order(self):
        """Test placing a limit order."""
        order_data = {
            "symbol": "BTC/USD",
            "side": "BUY",
            "type": "LIMIT",
            "price": "49000",
            "quantity": "0.5",
        }
        resp = await self.client.request(
            "POST",
            "/api/v1/orders",
            json=order_data,
            headers={"X-Session-ID": "test-session"},
        )
        assert resp.status == 201
        data = await resp.json()
        assert "order_id" in data
        assert data["symbol"] == "BTC/USD"
        assert data["side"] == "BUY"
        assert data["type"] == "LIMIT"
        assert data["status"] == "OPEN"
        assert data["price"] == "49000"
        assert data["quantity"] == "0.5"

    @unittest_run_loop
    async def test_place_market_order(self):
        """Test placing a market order."""
        order_data = {
            "symbol": "BTC/USD",
            "side": "SELL",
            "type": "MARKET",
            "quantity": "0.1",
        }
        resp = await self.client.request(
            "POST",
            "/api/v1/orders",
            json=order_data,
            headers={"X-Session-ID": "test-session"},
        )
        assert resp.status == 201
        data = await resp.json()
        assert data["type"] == "MARKET"

    @unittest_run_loop
    async def test_place_order_missing_fields(self):
        """Test placing order with missing required fields."""
        order_data = {"symbol": "BTC/USD", "side": "BUY"}
        resp = await self.client.request("POST", "/api/v1/orders", json=order_data)
        assert resp.status == 400
        data = await resp.json()
        assert "error" in data
        assert "Missing required fields" in data["error"]

    @unittest_run_loop
    async def test_place_limit_order_without_price(self):
        """Test placing limit order without price."""
        order_data = {
            "symbol": "BTC/USD",
            "side": "BUY",
            "type": "LIMIT",
            "quantity": "0.5",
        }
        resp = await self.client.request("POST", "/api/v1/orders", json=order_data)
        assert resp.status == 400
        data = await resp.json()
        assert "price required for LIMIT orders" in data["error"]

    @unittest_run_loop
    async def test_get_order(self):
        """Test getting order details."""
        # First place an order
        order_data = {
            "symbol": "BTC/USD",
            "side": "BUY",
            "type": "LIMIT",
            "price": "49000",
            "quantity": "0.5",
        }
        resp = await self.client.request(
            "POST",
            "/api/v1/orders",
            json=order_data,
            headers={"X-Session-ID": "test-session"},
        )
        data = await resp.json()
        order_id = data["order_id"]

        # Get the order
        resp = await self.client.request(
            "GET",
            f"/api/v1/orders/{order_id}",
            headers={"X-Session-ID": "test-session"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["order_id"] == order_id
        assert data["symbol"] == "BTC/USD"

    @unittest_run_loop
    async def test_get_order_not_found(self):
        """Test getting non-existent order."""
        resp = await self.client.request(
            "GET",
            "/api/v1/orders/nonexistent",
            headers={"X-Session-ID": "test-session"},
        )
        assert resp.status == 404
        data = await resp.json()
        assert "error" in data

    @unittest_run_loop
    async def test_get_orders(self):
        """Test getting all orders."""
        # Place multiple orders
        for i in range(3):
            order_data = {
                "symbol": "BTC/USD",
                "side": "BUY",
                "type": "LIMIT",
                "price": str(49000 + i * 100),
                "quantity": "0.1",
            }
            await self.client.request(
                "POST",
                "/api/v1/orders",
                json=order_data,
                headers={"X-Session-ID": "test-session"},
            )

        # Get all orders
        resp = await self.client.request(
            "GET", "/api/v1/orders", headers={"X-Session-ID": "test-session"}
        )
        assert resp.status == 200
        data = await resp.json()
        assert "orders" in data
        assert len(data["orders"]) == 3

    @unittest_run_loop
    async def test_get_orders_filtered_by_symbol(self):
        """Test getting orders filtered by symbol."""
        resp = await self.client.request(
            "GET",
            "/api/v1/orders?symbol=BTC/USD",
            headers={"X-Session-ID": "test-session"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert "orders" in data

    @unittest_run_loop
    async def test_get_orders_filtered_by_status(self):
        """Test getting orders filtered by status."""
        resp = await self.client.request(
            "GET", "/api/v1/orders?status=OPEN", headers={"X-Session-ID": "test-session"}
        )
        assert resp.status == 200
        data = await resp.json()
        assert "orders" in data

    @unittest_run_loop
    async def test_cancel_order(self):
        """Test cancelling an order."""
        # Place an order
        order_data = {
            "symbol": "BTC/USD",
            "side": "BUY",
            "type": "LIMIT",
            "price": "49000",
            "quantity": "0.5",
        }
        resp = await self.client.request(
            "POST",
            "/api/v1/orders",
            json=order_data,
            headers={"X-Session-ID": "test-session"},
        )
        data = await resp.json()
        order_id = data["order_id"]

        # Cancel the order
        resp = await self.client.request(
            "DELETE",
            f"/api/v1/orders/{order_id}",
            headers={"X-Session-ID": "test-session"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["order_id"] == order_id
        assert data["status"] == "cancelled"

    @unittest_run_loop
    async def test_cancel_order_not_found(self):
        """Test cancelling non-existent order."""
        resp = await self.client.request(
            "DELETE",
            "/api/v1/orders/nonexistent",
            headers={"X-Session-ID": "test-session"},
        )
        assert resp.status == 404
        data = await resp.json()
        assert "error" in data

    @unittest_run_loop
    async def test_get_balance(self):
        """Test getting account balance."""
        resp = await self.client.request(
            "GET", "/api/v1/balance", headers={"X-Session-ID": "test-session"}
        )
        assert resp.status == 200
        data = await resp.json()
        assert "balances" in data
        assert "USD" in data["balances"]
        assert "BTC" in data["balances"]
        assert data["balances"]["USD"] == "100000"
        assert data["balances"]["BTC"] == "10"

    @unittest_run_loop
    async def test_get_position(self):
        """Test getting position for a symbol."""
        resp = await self.client.request(
            "GET",
            "/api/v1/position?symbol=BTC/USD",
            headers={"X-Session-ID": "test-session"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["symbol"] == "BTC/USD"
        assert data["asset"] == "BTC"
        assert "quantity" in data

    @unittest_run_loop
    async def test_get_position_missing_symbol(self):
        """Test getting position without symbol parameter."""
        resp = await self.client.request(
            "GET", "/api/v1/position", headers={"X-Session-ID": "test-session"}
        )
        assert resp.status == 400
        data = await resp.json()
        assert "error" in data

    @unittest_run_loop
    async def test_get_price_history(self):
        """Test fetching raw price history."""
        generator = self.market_data_publisher.get_generator("BTC/USD")
        generator.set_price(Decimal("50500"))
        generator.set_price(Decimal("51000"))

        resp = await self.client.request(
            "GET", "/api/v1/prices?symbol=BTC/USD&limit=2"
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["symbol"] == "BTC/USD"
        assert "prices" in data
        assert len(data["prices"]) <= 2
        assert all("timestamp" in p and "price" in p for p in data["prices"])

    @unittest_run_loop
    async def test_get_price_history_invalid_symbol(self):
        """Test price history endpoint with invalid symbol."""
        resp = await self.client.request("GET", "/api/v1/prices?symbol=INVALID")
        assert resp.status == 404
        data = await resp.json()
        assert "error" in data

    @unittest_run_loop
    async def test_session_isolation(self):
        """Test that different sessions have isolated orders."""
        # Place order in session 1
        order_data = {
            "symbol": "BTC/USD",
            "side": "BUY",
            "type": "LIMIT",
            "price": "49000",
            "quantity": "0.5",
        }
        await self.client.request(
            "POST",
            "/api/v1/orders",
            json=order_data,
            headers={"X-Session-ID": "session-1"},
        )

        # Get orders for session 2
        resp = await self.client.request(
            "GET", "/api/v1/orders", headers={"X-Session-ID": "session-2"}
        )
        data = await resp.json()
        # Session 2 should not see session 1's orders
        assert len(data["orders"]) == 0
