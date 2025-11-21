"""REST/WebSocket reconciliation logic."""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Callable, Dict, Any, List

import aiohttp

from .sequence_tracker import Gap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .rate_limiter import RestRateLimiter


logger = logging.getLogger(__name__)


class Reconciler:
    """Handles reconciliation between REST API and WebSocket data."""

    def __init__(
        self,
        base_url: str,
        session_id: str,
        rate_limiter: "RestRateLimiter",  # type: ignore
        on_market_data_reconciled: Optional[
            Callable[[str, Dict[str, Any]], None]
        ] = None,
        on_price_history_reconciled: Optional[
            Callable[[str, List[Dict[str, Any]]], None]
        ] = None,
        on_orders_reconciled: Optional[Callable[[List[Dict]], None]] = None,
        on_balance_reconciled: Optional[Callable[[Dict[str, str]], None]] = None,
    ):
        """Initialize reconciler.

        Args:
            base_url: Server base URL
            session_id: Session ID for REST requests
            rate_limiter: Rate limiter instance
            on_market_data_reconciled: Callback when market data is reconciled
            on_orders_reconciled: Callback when orders are reconciled
            on_balance_reconciled: Callback when balance is reconciled
        """
        self.base_url = base_url
        self.session_id = session_id
        self.rate_limiter = rate_limiter
        self.on_market_data_reconciled = on_market_data_reconciled
        self.on_price_history_reconciled = on_price_history_reconciled
        self.on_orders_reconciled = on_orders_reconciled
        self.on_balance_reconciled = on_balance_reconciled
        self._http_session: Optional[aiohttp.ClientSession] = None

    async def _get_http_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def reconcile_market_data(self, symbol: str, gap: Gap) -> None:
        """Reconcile market data after detecting a gap.

        Args:
            symbol: Trading symbol
            gap: Gap information
        """
        try:
            session = await self._get_http_session()
            endpoint = f"/api/v1/ticker?symbol={symbol}"

            async def make_request():
                url = f"{self.base_url}{endpoint}"
                logger.info("REST GET %s", url)
                return await session.get(
                    url,
                    headers={"X-Session-ID": self.session_id},
                )

            response = await self.rate_limiter.retry_request(
                make_request, endpoint, max_retries=3
            )

            if response.status == 200:
                data = await response.json()
                if self.on_market_data_reconciled:
                    self.on_market_data_reconciled(symbol, data)
        except Exception as e:
            logger.error(f"Market data reconciliation failed for {symbol}: {e}")

    async def reconcile_orders(self) -> None:
        """Reconcile orders via REST API."""
        try:
            session = await self._get_http_session()
            endpoint = "/api/v1/orders"

            async def make_request():
                url = f"{self.base_url}{endpoint}"
                logger.info("REST GET %s", url)
                return await session.get(
                    url,
                    headers={"X-Session-ID": self.session_id},
                )

            response = await self.rate_limiter.retry_request(
                make_request, endpoint, max_retries=3
            )

            if response.status == 200:
                data = await response.json()
                orders = data.get("orders", [])
                if self.on_orders_reconciled:
                    self.on_orders_reconciled(orders)
        except Exception as e:
            logger.error(f"Orders reconciliation failed: {e}")

    async def reconcile_balance(self) -> None:
        """Reconcile balance via REST API."""
        try:
            session = await self._get_http_session()
            endpoint = "/api/v1/balance"

            async def make_request():
                url = f"{self.base_url}{endpoint}"
                logger.info("REST GET %s", url)
                return await session.get(
                    url,
                    headers={"X-Session-ID": self.session_id},
                )

            response = await self.rate_limiter.retry_request(
                make_request, endpoint, max_retries=3
            )

            if response.status == 200:
                data = await response.json()
                balances = data.get("balances", {})
                if self.on_balance_reconciled:
                    self.on_balance_reconciled(balances)
        except Exception as e:
            logger.error(f"Balance reconciliation failed: {e}")

    async def reconcile_all(self) -> None:
        """Perform full reconciliation (orders + balance)."""
        await asyncio.gather(
            self.reconcile_orders(),
            self.reconcile_balance(),
            return_exceptions=True,
        )

    async def reconcile_price_history(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> None:
        """Fetch raw price history for a symbol."""
        try:
            session = await self._get_http_session()
            endpoint = "/api/v1/prices"
            params = {"symbol": symbol}
            if start:
                params["start"] = start.isoformat()
            if end:
                params["end"] = end.isoformat()
            if limit:
                params["limit"] = str(limit)

            async def make_request():
                url = f"{self.base_url}{endpoint}"
                logger.info("REST GET %s params=%s", url, params)
                return await session.get(
                    url,
                    headers={"X-Session-ID": self.session_id},
                    params=params,
                )

            response = await self.rate_limiter.retry_request(
                make_request, endpoint, max_retries=3
            )

            if response.status == 200:
                data = await response.json()
                prices = data.get("prices", [])
                if self.on_price_history_reconciled:
                    self.on_price_history_reconciled(symbol, prices)
                logger.info(
                    "Fetched %d historical prices for %s", len(prices), symbol
                )
            else:
                logger.warning(
                    "Price history request failed (%s) for %s",
                    response.status,
                    symbol,
                )
        except Exception as e:
            logger.error(f"Price history reconciliation failed for {symbol}: {e}")

    async def close(self) -> None:
        """Close HTTP session."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

