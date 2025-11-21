"""Sequence ID tracking for gap detection."""

from typing import Dict, Optional, Tuple
from threading import Lock
from dataclasses import dataclass


@dataclass
class Gap:
    """Represents a sequence gap."""

    channel: str
    symbol: str
    start_seq: int
    end_seq: int

    def __repr__(self) -> str:
        return f"Gap(channel={self.channel}, symbol={self.symbol}, seq={self.start_seq}..{self.end_seq})"


class SequenceTracker:
    """Tracks sequence IDs per channel/symbol pair for gap detection."""

    def __init__(self):
        """Initialize sequence tracker."""
        self._expected_sequences: Dict[Tuple[str, str], int] = {}
        self._lock = Lock()

    def update(
        self, channel: str, symbol: str, sequence_id: int
    ) -> Optional[Gap]:
        """Update sequence tracking and detect gaps.

        Args:
            channel: Channel name (e.g., "TICKER")
            symbol: Trading symbol (e.g., "BTC/USD")
            sequence_id: Received sequence ID

        Returns:
            Gap object if gap detected, None otherwise
        """
        with self._lock:
            key = (channel, symbol)
            expected = self._expected_sequences.get(key, 1)

            if sequence_id < expected:
                # Out of order or duplicate - ignore
                return None

            if sequence_id > expected:
                # Gap detected
                gap = Gap(
                    channel=channel,
                    symbol=symbol,
                    start_seq=expected,
                    end_seq=sequence_id - 1,
                )
                self._expected_sequences[key] = sequence_id + 1
                return gap

            # Expected sequence - no gap
            self._expected_sequences[key] = sequence_id + 1
            return None

    def get_expected(self, channel: str, symbol: str) -> int:
        """Get next expected sequence ID.

        Args:
            channel: Channel name
            symbol: Trading symbol

        Returns:
            Next expected sequence ID (default: 1)
        """
        with self._lock:
            key = (channel, symbol)
            return self._expected_sequences.get(key, 1)

    def reset(self, channel: str, symbol: str) -> None:
        """Reset sequence tracking for a channel/symbol.

        Args:
            channel: Channel name
            symbol: Trading symbol
        """
        with self._lock:
            key = (channel, symbol)
            if key in self._expected_sequences:
                del self._expected_sequences[key]

    def reset_all(self) -> None:
        """Reset all sequence tracking."""
        with self._lock:
            self._expected_sequences.clear()

