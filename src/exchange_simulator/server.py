"""WebSocket server for the exchange simulator."""

import asyncio
import logging
from typing import Optional
from websockets.server import serve, WebSocketServerProtocol

from .config import Config
from .connection_manager import ConnectionManager
from .message_router import MessageRouter
from .failure_injector import FailureInjector
from .engine.exchange import ExchangeEngine
from .engine.accounts import AccountManager
from .market_data.generator import MarketDataGenerator, MarketDataPublisher, RandomWalkModel
from .handlers.order import OrderHandler
from .handlers.subscription import SubscriptionHandler
from .handlers.heartbeat import HeartbeatHandler
from .failures.strategies import (
    DropMessageStrategy,
    DelayMessageStrategy,
    DuplicateMessageStrategy,
    ReorderMessagesStrategy,
    CorruptMessageStrategy,
    ThrottleMessageStrategy,
)
from .models.messages import MessageType

logger = logging.getLogger(__name__)


class ExchangeServer:
    """WebSocket server for the exchange simulator."""

    def __init__(self, config: Config) -> None:
        """Initialize the exchange server.

        Args:
            config: Server configuration
        """
        self.config = config
        self.connection_manager = ConnectionManager()
        self.message_router = MessageRouter()
        self.failure_injector = FailureInjector()

        # Initialize exchange engine
        account_manager = AccountManager(
            default_balance=config.get_default_balance_decimal()
        )
        self.exchange_engine = ExchangeEngine(
            symbols=config.exchange.symbols,
            account_manager=account_manager,
        )

        # Initialize market data
        self.market_data_publisher = MarketDataPublisher()
        initial_prices = config.get_initial_prices_decimal()
        for symbol in config.exchange.symbols:
            initial_price = initial_prices.get(symbol)
            if initial_price:
                generator = MarketDataGenerator(
                    symbol=symbol,
                    initial_price=initial_price,
                    tick_interval=config.exchange.tick_interval,
                    price_model=RandomWalkModel(volatility=0.001),
                )
                self.market_data_publisher.add_generator(generator)
                self.exchange_engine.set_last_price(symbol, initial_price)

        # Register message handlers
        self._register_handlers()

        # Configure failure injection
        if config.failures.enabled:
            self._configure_failures()
        else:
            self.failure_injector.disable()

        self._server = None
        self._running = False

    def _register_handlers(self) -> None:
        """Register message handlers."""
        order_handler = OrderHandler(self.exchange_engine)
        subscription_handler = SubscriptionHandler(self.connection_manager)
        heartbeat_handler = HeartbeatHandler()

        # Register handlers for different message types
        self.message_router.register_handler(MessageType.PLACE_ORDER, order_handler)
        self.message_router.register_handler(MessageType.CANCEL_ORDER, order_handler)
        self.message_router.register_handler(MessageType.GET_ORDER, order_handler)
        self.message_router.register_handler(MessageType.GET_ORDERS, order_handler)
        self.message_router.register_handler(MessageType.SUBSCRIBE, subscription_handler)
        self.message_router.register_handler(MessageType.UNSUBSCRIBE, subscription_handler)
        self.message_router.register_handler(MessageType.PING, heartbeat_handler)

    def _configure_failures(self) -> None:
        """Configure failure injection strategies."""
        for mode_name, mode_config in self.config.failures.modes.items():
            if not mode_config.enabled:
                continue

            if mode_name == "drop_messages" and mode_config.probability is not None:
                strategy = DropMessageStrategy(probability=mode_config.probability)
                self.failure_injector.add_inbound_strategy(strategy)
                self.failure_injector.add_outbound_strategy(strategy)

            elif mode_name == "delay_messages" and mode_config.min_ms is not None and mode_config.max_ms is not None:
                strategy = DelayMessageStrategy(
                    min_ms=mode_config.min_ms,
                    max_ms=mode_config.max_ms,
                )
                self.failure_injector.add_outbound_strategy(strategy)

            elif mode_name == "duplicate_messages" and mode_config.probability is not None:
                strategy = DuplicateMessageStrategy(
                    probability=mode_config.probability,
                    max_duplicates=mode_config.max_duplicates or 2,
                )
                self.failure_injector.add_outbound_strategy(strategy)

            elif mode_name == "reorder_messages" and mode_config.window_size is not None:
                strategy = ReorderMessagesStrategy(window_size=mode_config.window_size)
                self.failure_injector.add_inbound_strategy(strategy)

            elif mode_name == "corrupt_messages" and mode_config.probability is not None:
                strategy = CorruptMessageStrategy(
                    probability=mode_config.probability,
                    corruption_level=mode_config.corruption_level or 0.1,
                )
                self.failure_injector.add_outbound_strategy(strategy)

            elif mode_name == "throttle_messages" and mode_config.max_messages_per_second is not None:
                strategy = ThrottleMessageStrategy(
                    max_messages_per_second=mode_config.max_messages_per_second
                )
                self.failure_injector.add_inbound_strategy(strategy)

    async def _handle_client(self, websocket: WebSocketServerProtocol) -> None:
        """Handle a client connection.

        Args:
            websocket: WebSocket connection
        """
        session_id = await self.connection_manager.add_connection(websocket)
        logger.info(f"Client connected: {session_id}")

        try:
            async for raw_message in websocket:
                if isinstance(raw_message, str):
                    await self._process_message(raw_message, session_id)
                else:
                    logger.warning(f"Received non-text message from {session_id}")

        except Exception as e:
            logger.error(f"Error handling client {session_id}: {e}")
        finally:
            await self.connection_manager.remove_connection(session_id)
            logger.info(f"Client disconnected: {session_id}")

    async def _process_message(self, raw_message: str, session_id: str) -> None:
        """Process a message from a client.

        Args:
            raw_message: Raw message string
            session_id: Client session ID
        """
        # Apply inbound failure injection
        processed_message = await self.failure_injector.inject_inbound(
            raw_message, session_id
        )

        if processed_message is None:
            # Message was dropped
            logger.debug(f"Inbound message dropped for {session_id}")
            return

        # Update activity
        await self.connection_manager.update_activity(session_id)

        # Route message to handler
        response = await self.message_router.route(processed_message, session_id)

        if response:
            # Serialize response
            response_str = self.message_router.serialize_message(response)

            # Apply outbound failure injection
            final_message = await self.failure_injector.inject_outbound(
                response_str, session_id
            )

            if final_message is not None:
                # Send response
                await self.connection_manager.send_to_session(session_id, final_message)
            else:
                logger.debug(f"Outbound message dropped for {session_id}")

    async def start(self) -> None:
        """Start the WebSocket server."""
        if self._running:
            logger.warning("Server is already running")
            return

        logger.info(f"Starting server on {self.config.server.host}:{self.config.server.port}")

        # Start market data generators
        self.market_data_publisher.start_all()

        # Start WebSocket server
        self._server = await serve(
            self._handle_client,
            self.config.server.host,
            self.config.server.port,
        )

        self._running = True
        logger.info("Server started successfully")

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if not self._running:
            return

        logger.info("Stopping server...")

        # Stop market data generators
        await self.market_data_publisher.stop_all()

        # Close all client connections
        await self.connection_manager.close_all()

        # Stop WebSocket server
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        self._running = False
        logger.info("Server stopped")

    async def run_forever(self) -> None:
        """Start server and run forever."""
        await self.start()
        try:
            await asyncio.Future()  # Run forever
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        finally:
            await self.stop()


async def main() -> None:
    """Main entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Create default configuration
    config = Config()

    # Create and run server
    server = ExchangeServer(config)
    await server.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
