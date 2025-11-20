"""Failure injector middleware for simulating network issues."""

from typing import List, Optional, Dict, Any
from .failures.strategies import FailureStrategy, FailureContext


class FailureInjector:
    """Middleware for injecting failures into message pipeline."""

    def __init__(self) -> None:
        """Initialize the failure injector."""
        self._inbound_strategies: List[FailureStrategy] = []
        self._outbound_strategies: List[FailureStrategy] = []
        self._enabled = True

    def add_inbound_strategy(self, strategy: FailureStrategy) -> None:
        """Add a failure strategy for inbound messages.

        Args:
            strategy: The failure strategy to add
        """
        self._inbound_strategies.append(strategy)

    def add_outbound_strategy(self, strategy: FailureStrategy) -> None:
        """Add a failure strategy for outbound messages.

        Args:
            strategy: The failure strategy to add
        """
        self._outbound_strategies.append(strategy)

    def remove_inbound_strategy(self, strategy: FailureStrategy) -> bool:
        """Remove an inbound failure strategy.

        Args:
            strategy: The strategy to remove

        Returns:
            True if removed, False if not found
        """
        try:
            self._inbound_strategies.remove(strategy)
            return True
        except ValueError:
            return False

    def remove_outbound_strategy(self, strategy: FailureStrategy) -> bool:
        """Remove an outbound failure strategy.

        Args:
            strategy: The strategy to remove

        Returns:
            True if removed, False if not found
        """
        try:
            self._outbound_strategies.remove(strategy)
            return True
        except ValueError:
            return False

    def clear_strategies(self) -> None:
        """Clear all failure strategies."""
        self._inbound_strategies.clear()
        self._outbound_strategies.clear()

    def reset_strategies(self) -> None:
        """Reset all failure strategies to their initial state."""
        for strategy in self._inbound_strategies:
            strategy.reset()
        for strategy in self._outbound_strategies:
            strategy.reset()

    def enable(self) -> None:
        """Enable failure injection."""
        self._enabled = True

    def disable(self) -> None:
        """Disable failure injection."""
        self._enabled = False

    def is_enabled(self) -> bool:
        """Check if failure injection is enabled.

        Returns:
            True if enabled, False otherwise
        """
        return self._enabled

    async def inject_inbound(
        self,
        message: str,
        session_id: str,
        message_type: str = "UNKNOWN",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Apply failure strategies to an inbound message.

        Args:
            message: The message to process
            session_id: Session ID of the sender
            message_type: Type of message
            metadata: Additional metadata

        Returns:
            The message after applying strategies, or None if dropped
        """
        if not self._enabled or not self._inbound_strategies:
            return message

        context = FailureContext(
            session_id=session_id,
            message_type=message_type,
            direction="inbound",
            metadata=metadata or {},
        )

        current_message = message
        for strategy in self._inbound_strategies:
            current_message = await strategy.apply(current_message, context)
            if current_message is None:
                # Message was dropped by this strategy
                return None

        return current_message

    async def inject_outbound(
        self,
        message: str,
        session_id: str,
        message_type: str = "UNKNOWN",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Apply failure strategies to an outbound message.

        Args:
            message: The message to process
            session_id: Session ID of the recipient
            message_type: Type of message
            metadata: Additional metadata

        Returns:
            The message after applying strategies, or None if dropped
        """
        if not self._enabled or not self._outbound_strategies:
            return message

        context = FailureContext(
            session_id=session_id,
            message_type=message_type,
            direction="outbound",
            metadata=metadata or {},
        )

        current_message = message
        for strategy in self._outbound_strategies:
            current_message = await strategy.apply(current_message, context)
            if current_message is None:
                # Message was dropped by this strategy
                return None

        return current_message

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics from all failure strategies.

        Returns:
            Dictionary containing statistics from all strategies
        """
        stats = {
            "inbound": {},
            "outbound": {},
            "enabled": self._enabled,
        }

        for i, strategy in enumerate(self._inbound_strategies):
            strategy_name = f"{type(strategy).__name__}_{i}"
            if hasattr(strategy, "get_stats"):
                stats["inbound"][strategy_name] = strategy.get_stats()

        for i, strategy in enumerate(self._outbound_strategies):
            strategy_name = f"{type(strategy).__name__}_{i}"
            if hasattr(strategy, "get_stats"):
                stats["outbound"][strategy_name] = strategy.get_stats()

        return stats

    def get_inbound_strategy_count(self) -> int:
        """Get the number of inbound strategies.

        Returns:
            Number of inbound strategies
        """
        return len(self._inbound_strategies)

    def get_outbound_strategy_count(self) -> int:
        """Get the number of outbound strategies.

        Returns:
            Number of outbound strategies
        """
        return len(self._outbound_strategies)
