"""Message router for handling incoming WebSocket messages."""

import json
from typing import Dict, Type, Optional, Any
from abc import ABC, abstractmethod

from .models.messages import (
    Message,
    MessageType,
    ErrorMessage,
    PlaceOrderMessage,
    CancelOrderMessage,
    GetOrderMessage,
    GetOrdersMessage,
    GetBalanceMessage,
    GetPositionMessage,
    SubscribeMessage,
    UnsubscribeMessage,
    PingMessage,
)


class MessageHandler(ABC):
    """Abstract base class for message handlers."""

    @abstractmethod
    async def handle(self, message: Message, session_id: str) -> Optional[Message]:
        """Handle a message.

        Args:
            message: The message to handle
            session_id: Session ID of the sender

        Returns:
            Optional response message
        """
        pass


class MessageRouter:
    """Routes incoming messages to appropriate handlers."""

    # Map of message types to their corresponding Pydantic models
    MESSAGE_TYPE_MAP: Dict[MessageType, Type[Message]] = {
        MessageType.PLACE_ORDER: PlaceOrderMessage,
        MessageType.CANCEL_ORDER: CancelOrderMessage,
        MessageType.GET_ORDER: GetOrderMessage,
        MessageType.GET_ORDERS: GetOrdersMessage,
        MessageType.GET_BALANCE: GetBalanceMessage,
        MessageType.GET_POSITION: GetPositionMessage,
        MessageType.SUBSCRIBE: SubscribeMessage,
        MessageType.UNSUBSCRIBE: UnsubscribeMessage,
        MessageType.PING: PingMessage,
    }

    def __init__(self) -> None:
        """Initialize the message router."""
        self._handlers: Dict[MessageType, MessageHandler] = {}

    def register_handler(self, message_type: MessageType, handler: MessageHandler) -> None:
        """Register a handler for a message type.

        Args:
            message_type: Type of message to handle
            handler: Handler instance
        """
        self._handlers[message_type] = handler

    def unregister_handler(self, message_type: MessageType) -> None:
        """Unregister a handler for a message type.

        Args:
            message_type: Type of message to unregister
        """
        self._handlers.pop(message_type, None)

    def get_handler(self, message_type: MessageType) -> Optional[MessageHandler]:
        """Get the handler for a message type.

        Args:
            message_type: Type of message

        Returns:
            Handler instance or None if not registered
        """
        return self._handlers.get(message_type)

    async def parse_message(self, raw_message: str) -> Message:
        """Parse a raw JSON message into a typed Message object.

        Args:
            raw_message: Raw JSON string

        Returns:
            Parsed Message object

        Raises:
            ValueError: If message cannot be parsed
        """
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")

        if not isinstance(data, dict):
            raise ValueError("Message must be a JSON object")

        if "type" not in data:
            raise ValueError("Message must have a 'type' field")

        try:
            message_type = MessageType(data["type"])
        except ValueError:
            raise ValueError(f"Unknown message type: {data['type']}")

        message_class = self.MESSAGE_TYPE_MAP.get(message_type)
        if not message_class:
            raise ValueError(f"Unsupported message type: {message_type}")

        try:
            return message_class.model_validate(data)
        except Exception as e:
            raise ValueError(f"Invalid message format: {e}")

    async def route(self, raw_message: str, session_id: str) -> Optional[Message]:
        """Route a raw message to the appropriate handler.

        Args:
            raw_message: Raw JSON message string
            session_id: Session ID of the sender

        Returns:
            Optional response message
        """
        try:
            message = await self.parse_message(raw_message)
        except ValueError as e:
            return ErrorMessage(
                code="INVALID_MESSAGE",
                message=str(e),
            )

        handler = self._handlers.get(message.type)
        if not handler:
            return ErrorMessage(
                code="NO_HANDLER",
                message=f"No handler registered for message type: {message.type}",
            )

        try:
            return await handler.handle(message, session_id)
        except Exception as e:
            return ErrorMessage(
                code="HANDLER_ERROR",
                message=f"Error handling message: {str(e)}",
                details={"message_type": message.type.value},
            )

    def serialize_message(self, message: Message) -> str:
        """Serialize a message to JSON.

        Args:
            message: Message to serialize

        Returns:
            JSON string
        """
        return message.model_dump_json()
