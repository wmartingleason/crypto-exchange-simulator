"""Exchange simulator server."""

import asyncio
import logging
from typing import Optional
from aiohttp import web
import aiohttp

from .config import Config
from .engine.exchange import ExchangeEngine
from .engine.accounts import AccountManager
from .connection_manager import ConnectionManager
from .message_router import MessageRouter
from .failure_injector import FailureInjector
from .market_data.generator import MarketDataPublisher, RandomWalkModel, GBMPriceModel
from .rest_api import RestAPIHandler, create_rest_routes, RateLimiter
from .handlers.order import OrderHandler
from .handlers.subscription import SubscriptionHandler
from .models.messages import MessageType
from .failures.strategies import (
    DropMessageStrategy,
    DelayMessageStrategy,
    DuplicateMessageStrategy,
    ReorderMessagesStrategy,
    CorruptMessageStrategy,
    ThrottleMessageStrategy,
    RateLimitStrategy,
    HardcodedVolumeDetector,
    LatencySimulationStrategy,
    SilentConnectionStrategy,
    FailureContext,
)

logger = logging.getLogger(__name__)


class ExchangeServer:
    """Exchange simulator server."""

    def __init__(self, config: Config):
        self.config = config
        self.app = web.Application()
        self._runner = None
        self._site = None
        self._running = False
        self._market_data_task = None
        self._latency_strategy = None

        self.account_manager = AccountManager(config.exchange.default_balance)
        self.exchange_engine = ExchangeEngine(
            symbols=config.exchange.symbols,
            account_manager=self.account_manager,
        )
        self.connection_manager = ConnectionManager()
        self.message_router = MessageRouter()
        self.failure_injector = FailureInjector()
        self._silent_connection_strategy: Optional[SilentConnectionStrategy] = None

        self.market_data_publisher = MarketDataPublisher()
        initial_prices = config.get_initial_prices_decimal()

        pricing_config = config.exchange.pricing_model
        if pricing_config.model_type == "gbm":
            from .market_data.generator import MarketDataGenerator
            price_model = GBMPriceModel(
                drift=pricing_config.drift,
                volatility=pricing_config.volatility,
                tick_interval_seconds=config.exchange.tick_interval,
            )
        else:
            price_model = RandomWalkModel(volatility=pricing_config.volatility)

        for symbol in config.exchange.symbols:
            initial_price = initial_prices.get(symbol)
            if initial_price:
                from .market_data.generator import MarketDataGenerator
                generator = MarketDataGenerator(
                    symbol=symbol,
                    initial_price=initial_price,
                    tick_interval=config.exchange.tick_interval,
                    price_model=price_model,
                )
                self.market_data_publisher.add_generator(generator)
                self.exchange_engine.set_last_price(symbol, initial_price)

        if config.failures.enabled:
            self._configure_failures()
        else:
            self.failure_injector.disable()

        self._configure_latency()

        self._register_handlers()
        self._setup_rest_api()
        self.app.router.add_get("/ws", self._handle_websocket)

    def _register_handlers(self) -> None:
        order_handler = OrderHandler(self.exchange_engine)
        subscription_handler = SubscriptionHandler(self.connection_manager)

        self.message_router.register_handler(MessageType.PLACE_ORDER, order_handler)
        self.message_router.register_handler(MessageType.CANCEL_ORDER, order_handler)
        self.message_router.register_handler(MessageType.GET_ORDER, order_handler)
        self.message_router.register_handler(MessageType.GET_ORDERS, order_handler)
        self.message_router.register_handler(MessageType.SUBSCRIBE, subscription_handler)
        self.message_router.register_handler(MessageType.UNSUBSCRIBE, subscription_handler)

    def _configure_latency(self) -> None:
        latency_config = self.config.failures.latency
        self._latency_strategy = LatencySimulationStrategy(
            mu=latency_config.mu,
            sigma=latency_config.sigma,
        )
        self.failure_injector.add_inbound_strategy(self._latency_strategy)
        self.failure_injector.add_outbound_strategy(self._latency_strategy)

    def _configure_failures(self) -> None:
        modes = self.config.failures.modes
        self._silent_connection_strategy = None

        drop_cfg = modes.get("drop_messages")
        if drop_cfg and drop_cfg.enabled:
            self.failure_injector.add_inbound_strategy(
                DropMessageStrategy(probability=drop_cfg.probability or 0.1)
            )

        delay_cfg = modes.get("delay_messages")
        if delay_cfg and delay_cfg.enabled:
            self.failure_injector.add_inbound_strategy(
                DelayMessageStrategy(
                    min_delay_ms=delay_cfg.min_ms or 100,
                    max_delay_ms=delay_cfg.max_ms or 1000,
                )
            )

        duplicate_cfg = modes.get("duplicate_messages")
        if duplicate_cfg and duplicate_cfg.enabled:
            self.failure_injector.add_outbound_strategy(
                DuplicateMessageStrategy(
                    probability=duplicate_cfg.probability or 0.05,
                    max_duplicates=duplicate_cfg.max_duplicates or 2,
                )
            )

        reorder_cfg = modes.get("reorder_messages")
        if reorder_cfg and reorder_cfg.enabled:
            self.failure_injector.add_inbound_strategy(
                ReorderMessagesStrategy(window_size=reorder_cfg.window_size or 5)
            )

        corrupt_cfg = modes.get("corrupt_messages")
        if corrupt_cfg and corrupt_cfg.enabled:
            self.failure_injector.add_outbound_strategy(
                CorruptMessageStrategy(
                    probability=corrupt_cfg.probability or 0.01,
                    corruption_level=corrupt_cfg.corruption_level or 0.1,
                )
            )

        throttle_cfg = modes.get("throttle_messages")
        if throttle_cfg and throttle_cfg.enabled:
            self.failure_injector.add_inbound_strategy(
                ThrottleMessageStrategy(
                    max_messages_per_second=throttle_cfg.max_messages_per_second or 10
                )
            )

        silent_cfg = modes.get("silent_connection")
        if silent_cfg and silent_cfg.enabled:
            self._silent_connection_strategy = SilentConnectionStrategy(
                enabled=True,
                after_messages=silent_cfg.after_messages or 0,
            )

    def _setup_rest_api(self) -> None:
        rate_limiter = None

        if self.config.failures.enabled:
            rate_limit_config = self.config.failures.modes.get("rate_limit")
            if rate_limit_config and rate_limit_config.enabled:
                volume_detector = HardcodedVolumeDetector(
                    high_volume=False,
                    volume_multiplier=0.5,
                )
                rate_limit_strategy = RateLimitStrategy(
                    baseline_rps=10,
                    wait_period_seconds=10,
                    second_violation_ban_seconds=60,
                    violation_window_seconds=60,
                    volume_detector=volume_detector,
                )
                rate_limiter = RateLimiter(rate_limit_strategy=rate_limit_strategy)

        rest_handler = RestAPIHandler(
            self.exchange_engine,
            self.account_manager,
            self.market_data_publisher,
            rate_limiter=rate_limiter,
            latency_strategy=self._latency_strategy,
        )
        routes = create_rest_routes(rest_handler)
        self.app.router.add_routes(routes)

    async def _apply_silent_strategy(
        self, message: Optional[str], session_id: str, message_type: str
    ) -> Optional[str]:
        if message is None or not self._silent_connection_strategy:
            return message

        context = FailureContext(
            session_id=session_id,
            message_type=message_type,
            direction="outbound",
        )
        return await self._silent_connection_strategy.apply(message, context)

    async def _apply_outbound_failures(
        self, message: str, session_id: str, message_type: str
    ) -> Optional[str]:
        processed = await self.failure_injector.inject_outbound(
            message, session_id, message_type
        )
        if processed is None:
            return None
        return await self._apply_silent_strategy(processed, session_id, message_type)

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        session_id = await self.connection_manager.add_connection(ws)
        logger.info(f"Client connected: {session_id}")

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    processed_msg = await self.failure_injector.inject_inbound(
                        msg.data, session_id
                    )

                    if processed_msg is None:
                        continue

                    response = await self.message_router.route(processed_msg, session_id)

                    if response:
                        response_str = self.message_router.serialize_message(response)
                        response_type = getattr(response, "type", None)
                        if response_type is not None:
                            message_type = (
                                response_type.value
                                if hasattr(response_type, "value")
                                else str(response_type)
                            )
                        else:
                            message_type = "UNKNOWN"
                        final_message = await self._apply_outbound_failures(
                            response_str, session_id, message_type
                        )

                        if final_message is not None:
                            await self.connection_manager.send_to_session(
                                session_id, final_message
                            )

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")

        finally:
            await self.connection_manager.remove_connection(session_id)
            logger.info(f"Client disconnected: {session_id}")

        return ws

    async def _broadcast_market_data(self) -> None:
        while self._running:
            try:
                for symbol, generator in self.market_data_publisher.generators.items():
                    market_data = generator.get_market_data_message()
                    if market_data is None:
                        # Price hasn't changed, skip broadcasting
                        continue

                    message_str = self.message_router.serialize_message(market_data)
                    channel_key = f"TICKER:{symbol}"

                    final_message = await self.failure_injector.inject_outbound(
                        message_str, "broadcast", "MARKET_DATA"
                    )

                    if final_message is None:
                        continue

                    subscribed_sessions = self.connection_manager.get_subscribed_sessions(
                        channel_key
                    )
                    for session_id in subscribed_sessions:
                        session_message = await self._apply_silent_strategy(
                            final_message, session_id, "MARKET_DATA"
                        )
                        if session_message is None:
                            continue
                        await self.connection_manager.send_to_session(
                            session_id, session_message
                        )

                await asyncio.sleep(self.config.exchange.tick_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error broadcasting market data: {e}")
                await asyncio.sleep(1)

    async def start(self) -> None:
        if self._running:
            logger.warning("Server already running")
            return

        logger.info(f"Starting server on {self.config.server.host}:{self.config.server.port}")

        self.market_data_publisher.start_all()
        self._running = True
        self._market_data_task = asyncio.create_task(self._broadcast_market_data())

        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner, self.config.server.host, self.config.server.port
        )
        await self._site.start()

        logger.info("Server started")
        logger.info(f"REST API: http://{self.config.server.host}:{self.config.server.port}/api/v1")
        logger.info(f"WebSocket: ws://{self.config.server.host}:{self.config.server.port}/ws")

    async def stop(self) -> None:
        if not self._running:
            return

        logger.info("Stopping server...")
        self._running = False

        if self._market_data_task:
            self._market_data_task.cancel()
            try:
                await self._market_data_task
            except asyncio.CancelledError:
                pass

        await self.market_data_publisher.stop_all()
        await self.connection_manager.close_all()

        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

        logger.info("Server stopped")

    async def run_forever(self) -> None:
        await self.start()
        try:
            await asyncio.Future()
        except KeyboardInterrupt:
            logger.info("Interrupt received")
        finally:
            await self.stop()


async def main(config_path: Optional[str] = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if config_path:
        config = Config.from_file(config_path)
        logger.info(f"Loaded configuration from {config_path}")
    else:
        import os
        default_config = os.path.join(os.path.dirname(__file__), "config.json")
        if os.path.exists(default_config):
            config = Config.from_file(default_config)
            logger.info(f"Loaded configuration from {default_config}")
        else:
            config = Config()
            logger.info("Using default configuration")

    server = ExchangeServer(config)
    await server.run_forever()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Exchange simulator server")
    parser.add_argument(
        "--config",
        type=str,
        help="Path to configuration JSON file",
        default=None,
    )
    args = parser.parse_args()
    asyncio.run(main(args.config))
