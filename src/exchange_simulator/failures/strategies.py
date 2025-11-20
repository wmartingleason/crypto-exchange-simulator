"""Failure strategies for simulating network issues."""

import asyncio
import random
from abc import ABC, abstractmethod
from typing import Optional, Any, Dict
from collections import deque
from pydantic import BaseModel


class FailureContext(BaseModel):
    """Context information for failure injection."""

    session_id: str
    message_type: str
    direction: str  # 'inbound' or 'outbound'
    metadata: Dict[str, Any] = {}

    class Config:
        """Pydantic config."""
        arbitrary_types_allowed = True


class FailureStrategy(ABC):
    """Abstract base class for failure strategies."""

    @abstractmethod
    async def apply(self, message: str, context: FailureContext) -> Optional[str]:
        """Apply the failure strategy to a message.

        Args:
            message: The message to apply the strategy to
            context: Context information

        Returns:
            The message (possibly modified), or None if message should be dropped
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset the strategy state."""
        pass


class DropMessageStrategy(FailureStrategy):
    """Strategy that randomly drops messages."""

    def __init__(self, probability: float = 0.05) -> None:
        """Initialize the drop message strategy.

        Args:
            probability: Probability of dropping a message (0.0 to 1.0)
        """
        if not 0.0 <= probability <= 1.0:
            raise ValueError("Probability must be between 0.0 and 1.0")
        self.probability = probability
        self.dropped_count = 0

    async def apply(self, message: str, context: FailureContext) -> Optional[str]:
        """Drop message based on probability."""
        if random.random() < self.probability:
            self.dropped_count += 1
            return None
        return message

    def reset(self) -> None:
        """Reset the strategy state."""
        self.dropped_count = 0

    def get_stats(self) -> Dict[str, int]:
        """Get statistics about dropped messages."""
        return {"dropped_count": self.dropped_count}


class DelayMessageStrategy(FailureStrategy):
    """Strategy that adds random delay to messages."""

    def __init__(self, min_ms: int = 100, max_ms: int = 2000) -> None:
        """Initialize the delay message strategy.

        Args:
            min_ms: Minimum delay in milliseconds
            max_ms: Maximum delay in milliseconds
        """
        if min_ms < 0 or max_ms < 0:
            raise ValueError("Delays must be non-negative")
        if min_ms > max_ms:
            raise ValueError("min_ms must be <= max_ms")

        self.min_ms = min_ms
        self.max_ms = max_ms
        self.total_delay_ms = 0
        self.delayed_count = 0

    async def apply(self, message: str, context: FailureContext) -> Optional[str]:
        """Add random delay to message."""
        delay_ms = random.uniform(self.min_ms, self.max_ms)
        self.total_delay_ms += delay_ms
        self.delayed_count += 1

        await asyncio.sleep(delay_ms / 1000.0)
        return message

    def reset(self) -> None:
        """Reset the strategy state."""
        self.total_delay_ms = 0
        self.delayed_count = 0

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about delays."""
        avg_delay = self.total_delay_ms / self.delayed_count if self.delayed_count > 0 else 0
        return {
            "delayed_count": self.delayed_count,
            "total_delay_ms": self.total_delay_ms,
            "average_delay_ms": avg_delay,
        }


class DuplicateMessageStrategy(FailureStrategy):
    """Strategy that randomly duplicates messages."""

    def __init__(self, probability: float = 0.05, max_duplicates: int = 2) -> None:
        """Initialize the duplicate message strategy.

        Args:
            probability: Probability of duplicating a message
            max_duplicates: Maximum number of duplicates to create
        """
        if not 0.0 <= probability <= 1.0:
            raise ValueError("Probability must be between 0.0 and 1.0")
        if max_duplicates < 1:
            raise ValueError("max_duplicates must be at least 1")

        self.probability = probability
        self.max_duplicates = max_duplicates
        self.duplicated_count = 0
        self._pending_duplicates: deque = deque()

    async def apply(self, message: str, context: FailureContext) -> Optional[str]:
        """Duplicate message based on probability."""
        # First, check if we have pending duplicates from a previous message
        if self._pending_duplicates:
            return self._pending_duplicates.popleft()

        # Decide if we should duplicate this message
        if random.random() < self.probability:
            num_duplicates = random.randint(1, self.max_duplicates)
            self.duplicated_count += num_duplicates

            # Queue up the duplicates for subsequent calls
            for _ in range(num_duplicates):
                self._pending_duplicates.append(message)

        return message

    def reset(self) -> None:
        """Reset the strategy state."""
        self.duplicated_count = 0
        self._pending_duplicates.clear()

    def get_stats(self) -> Dict[str, int]:
        """Get statistics about duplicates."""
        return {"duplicated_count": self.duplicated_count}


class ReorderMessagesStrategy(FailureStrategy):
    """Strategy that reorders messages within a window."""

    def __init__(self, window_size: int = 5) -> None:
        """Initialize the reorder messages strategy.

        Args:
            window_size: Size of the reordering window
        """
        if window_size < 2:
            raise ValueError("window_size must be at least 2")

        self.window_size = window_size
        self._buffer: deque = deque(maxlen=window_size)
        self.reordered_count = 0

    async def apply(self, message: str, context: FailureContext) -> Optional[str]:
        """Reorder messages within a window."""
        self._buffer.append(message)

        # Only start delivering messages once buffer is full
        if len(self._buffer) >= self.window_size:
            # Randomly select a message from the buffer
            index = random.randint(0, len(self._buffer) - 1)
            selected = self._buffer[index]

            # Remove selected message and shift buffer
            temp_list = list(self._buffer)
            temp_list.pop(index)
            self._buffer = deque(temp_list, maxlen=self.window_size)

            if index != 0:  # If we didn't pick the first (oldest) message, we reordered
                self.reordered_count += 1

            return selected

        # Buffer not full yet, hold message
        return None

    def reset(self) -> None:
        """Reset the strategy state."""
        self._buffer.clear()
        self.reordered_count = 0

    def flush(self) -> list[str]:
        """Flush any remaining messages in the buffer.

        Returns:
            List of buffered messages
        """
        messages = list(self._buffer)
        self._buffer.clear()
        return messages

    def get_stats(self) -> Dict[str, int]:
        """Get statistics about reordering."""
        return {
            "reordered_count": self.reordered_count,
            "buffered_count": len(self._buffer),
        }


class CorruptMessageStrategy(FailureStrategy):
    """Strategy that corrupts message content."""

    def __init__(self, probability: float = 0.02, corruption_level: float = 0.1) -> None:
        """Initialize the corrupt message strategy.

        Args:
            probability: Probability of corrupting a message
            corruption_level: Fraction of message to corrupt (0.0 to 1.0)
        """
        if not 0.0 <= probability <= 1.0:
            raise ValueError("Probability must be between 0.0 and 1.0")
        if not 0.0 < corruption_level <= 1.0:
            raise ValueError("Corruption level must be between 0.0 and 1.0")

        self.probability = probability
        self.corruption_level = corruption_level
        self.corrupted_count = 0

    async def apply(self, message: str, context: FailureContext) -> Optional[str]:
        """Corrupt message content based on probability."""
        if random.random() < self.probability:
            self.corrupted_count += 1
            return self._corrupt(message)
        return message

    def _corrupt(self, message: str) -> str:
        """Corrupt the message by randomly modifying characters.

        Args:
            message: Original message

        Returns:
            Corrupted message
        """
        if not message:
            return message

        message_list = list(message)
        num_corruptions = max(1, int(len(message) * self.corruption_level))

        for _ in range(num_corruptions):
            if len(message_list) > 0:
                pos = random.randint(0, len(message_list) - 1)
                # Replace with random printable ASCII character
                message_list[pos] = chr(random.randint(33, 126))

        return "".join(message_list)

    def reset(self) -> None:
        """Reset the strategy state."""
        self.corrupted_count = 0

    def get_stats(self) -> Dict[str, int]:
        """Get statistics about corrupted messages."""
        return {"corrupted_count": self.corrupted_count}


class ThrottleMessageStrategy(FailureStrategy):
    """Strategy that throttles message rate."""

    def __init__(self, max_messages_per_second: int = 10) -> None:
        """Initialize the throttle message strategy.

        Args:
            max_messages_per_second: Maximum messages allowed per second
        """
        if max_messages_per_second < 1:
            raise ValueError("max_messages_per_second must be at least 1")

        self.max_messages_per_second = max_messages_per_second
        self.min_interval = 1.0 / max_messages_per_second
        self.last_message_time = 0.0
        self.throttled_count = 0

    async def apply(self, message: str, context: FailureContext) -> Optional[str]:
        """Throttle message rate."""
        import time

        current_time = time.time()
        time_since_last = current_time - self.last_message_time

        if time_since_last < self.min_interval:
            delay = self.min_interval - time_since_last
            self.throttled_count += 1
            await asyncio.sleep(delay)

        self.last_message_time = time.time()
        return message

    def reset(self) -> None:
        """Reset the strategy state."""
        self.last_message_time = 0.0
        self.throttled_count = 0

    def get_stats(self) -> Dict[str, int]:
        """Get statistics about throttling."""
        return {"throttled_count": self.throttled_count}
