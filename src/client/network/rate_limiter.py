"""REST API rate limiting with proactive and reactive handling."""

import asyncio
import time
from typing import Dict, Deque, Optional, Callable, Any
from collections import deque
from datetime import datetime, timedelta
import aiohttp


class RestRateLimiter:
    """REST API rate limiter with proactive tracking and reactive retry handling."""

    def __init__(
        self,
        proactive: bool = True,
        window_seconds: float = 60.0,
        initial_backoff: float = 1.0,
        max_backoff: float = 60.0,
        backoff_multiplier: float = 2.0,
    ):
        """Initialize rate limiter.

        Args:
            proactive: Enable proactive rate limiting
            window_seconds: Sliding window size in seconds
            initial_backoff: Initial backoff delay in seconds
            max_backoff: Maximum backoff delay in seconds
            backoff_multiplier: Backoff multiplier for exponential backoff
        """
        self.proactive = proactive
        self.window_seconds = window_seconds
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.backoff_multiplier = backoff_multiplier

        self._request_timestamps: Dict[str, Deque[float]] = {}
        self._rate_limit_state: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def check_rate_limit(
        self, endpoint: str, max_rps: Optional[float] = None
    ) -> None:
        """Proactively check rate limit and delay if necessary.

        Args:
            endpoint: API endpoint path
            max_rps: Maximum requests per second (None = no proactive limiting)
        """
        if not self.proactive or max_rps is None:
            return

        async with self._lock:
            now = time.time()
            window_start = now - self.window_seconds

            if endpoint not in self._request_timestamps:
                self._request_timestamps[endpoint] = deque()

            timestamps = self._request_timestamps[endpoint]

            # Remove old timestamps outside window
            while timestamps and timestamps[0] < window_start:
                timestamps.popleft()

            # Calculate current rate
            current_rate = len(timestamps) / self.window_seconds

            if current_rate >= max_rps:
                # Need to delay
                oldest_timestamp = timestamps[0] if timestamps else now
                next_allowed = oldest_timestamp + self.window_seconds
                delay = max(0, next_allowed - now)
                if delay > 0:
                    await asyncio.sleep(delay)

            # Record this request
            timestamps.append(time.time())

    async def handle_rate_limit_error(
        self, response: aiohttp.ClientResponse, endpoint: str
    ) -> float:
        """Handle HTTP 429 rate limit error.

        Args:
            response: HTTP response object
            endpoint: API endpoint path

        Returns:
            Retry delay in seconds
        """
        async with self._lock:
            # Extract Retry-After header if present
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return float(retry_after)
                except ValueError:
                    pass

            # Use exponential backoff
            if endpoint not in self._rate_limit_state:
                self._rate_limit_state[endpoint] = {
                    "retry_count": 0,
                    "last_error": None,
                }

            state = self._rate_limit_state[endpoint]
            state["retry_count"] += 1
            state["last_error"] = datetime.now()

            delay = min(
                self.initial_backoff
                * (self.backoff_multiplier ** (state["retry_count"] - 1)),
                self.max_backoff,
            )

            return delay

    async def retry_request(
        self,
        coro: Callable,
        endpoint: str,
        max_retries: int = 3,
        max_rps: Optional[float] = None,
    ) -> Any:
        """Execute request with automatic retry on rate limit errors.

        Args:
            coro: Coroutine function that makes the request
            endpoint: API endpoint path
            max_retries: Maximum number of retries
            max_rps: Maximum requests per second for proactive limiting

        Returns:
            Response from successful request

        Raises:
            aiohttp.ClientResponseError: If request fails after all retries
        """
        for attempt in range(max_retries + 1):
            try:
                await self.check_rate_limit(endpoint, max_rps)
                response = await coro()

                if response.status == 429:
                    delay = await self.handle_rate_limit_error(response, endpoint)
                    if attempt < max_retries:
                        await asyncio.sleep(delay)
                        continue
                    else:
                        response.raise_for_status()

                # Reset retry count on success
                async with self._lock:
                    if endpoint in self._rate_limit_state:
                        self._rate_limit_state[endpoint]["retry_count"] = 0

                return response

            except aiohttp.ClientResponseError as e:
                if e.status == 429 and attempt < max_retries:
                    # Create a mock response for handle_rate_limit_error
                    class MockResponse:
                        def __init__(self, status_code):
                            self.status = status_code
                            self.headers = {}

                    delay = await self.handle_rate_limit_error(
                        MockResponse(429), endpoint
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        raise Exception("Max retries exceeded")

    def reset_endpoint(self, endpoint: str) -> None:
        """Reset rate limit state for an endpoint.

        Args:
            endpoint: API endpoint path
        """
        async def _reset():
            async with self._lock:
                if endpoint in self._request_timestamps:
                    del self._request_timestamps[endpoint]
                if endpoint in self._rate_limit_state:
                    del self._rate_limit_state[endpoint]

        asyncio.create_task(_reset())

