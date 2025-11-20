"""Account management for the exchange."""

from decimal import Decimal
from typing import Dict, Optional
from ..models.orders import Position, Fill


class Account:
    """Represents a trading account."""

    def __init__(self, session_id: str, initial_balance: Optional[Dict[str, Decimal]] = None) -> None:
        """Initialize an account.

        Args:
            session_id: Session ID for this account
            initial_balance: Initial balance by currency
        """
        self.session_id = session_id
        self.balances: Dict[str, Decimal] = initial_balance or {}
        self.positions: Dict[str, Position] = {}
        self.margin_used = Decimal("0")
        self.margin_available = Decimal("0")

    def get_balance(self, currency: str) -> Decimal:
        """Get balance for a currency.

        Args:
            currency: Currency code

        Returns:
            Balance amount
        """
        return self.balances.get(currency, Decimal("0"))

    def set_balance(self, currency: str, amount: Decimal) -> None:
        """Set balance for a currency.

        Args:
            currency: Currency code
            amount: Balance amount
        """
        self.balances[currency] = amount

    def adjust_balance(self, currency: str, amount: Decimal) -> Decimal:
        """Adjust balance by a delta amount.

        Args:
            currency: Currency code
            amount: Amount to add (positive) or subtract (negative)

        Returns:
            New balance
        """
        current = self.get_balance(currency)
        new_balance = current + amount
        self.balances[currency] = new_balance
        return new_balance

    def has_sufficient_balance(self, currency: str, amount: Decimal) -> bool:
        """Check if account has sufficient balance.

        Args:
            currency: Currency code
            amount: Required amount

        Returns:
            True if balance is sufficient
        """
        return self.get_balance(currency) >= amount

    def get_position(self, symbol: str) -> Position:
        """Get or create a position for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Position object
        """
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        return self.positions[symbol]

    def update_position_on_fill(self, fill: Fill, current_price: Decimal) -> None:
        """Update position based on a fill.

        Args:
            fill: The fill to process
            current_price: Current market price for PnL calculation
        """
        position = self.get_position(fill.symbol)
        position.update_on_fill(fill)
        position.calculate_unrealized_pnl(current_price)

    def get_total_equity(self, market_prices: Dict[str, Decimal]) -> Decimal:
        """Calculate total account equity.

        Args:
            market_prices: Current market prices by symbol

        Returns:
            Total equity
        """
        # Start with cash balances
        equity = sum(self.balances.values())

        # Add unrealized PnL from all positions
        for symbol, position in self.positions.items():
            if symbol in market_prices:
                position.calculate_unrealized_pnl(market_prices[symbol])
                equity += position.unrealized_pnl
            equity += position.realized_pnl

        return equity


class AccountManager:
    """Manages all trading accounts."""

    def __init__(self, default_balance: Optional[Dict[str, Decimal]] = None) -> None:
        """Initialize the account manager.

        Args:
            default_balance: Default balance for new accounts
        """
        self._accounts: Dict[str, Account] = {}
        self._default_balance = default_balance or {"USD": Decimal("100000")}

    def create_account(
        self, session_id: str, initial_balance: Optional[Dict[str, Decimal]] = None
    ) -> Account:
        """Create a new account.

        Args:
            session_id: Session ID for the account
            initial_balance: Initial balance (uses default if not provided)

        Returns:
            Created account
        """
        if session_id in self._accounts:
            raise ValueError(f"Account already exists for session {session_id}")

        balance = initial_balance if initial_balance is not None else self._default_balance.copy()
        account = Account(session_id, balance)
        self._accounts[session_id] = account
        return account

    def get_account(self, session_id: str) -> Optional[Account]:
        """Get an account by session ID.

        Args:
            session_id: Session ID

        Returns:
            Account or None if not found
        """
        return self._accounts.get(session_id)

    def get_or_create_account(
        self, session_id: str, initial_balance: Optional[Dict[str, Decimal]] = None
    ) -> Account:
        """Get an existing account or create a new one.

        Args:
            session_id: Session ID
            initial_balance: Initial balance for new accounts

        Returns:
            Account object
        """
        account = self._accounts.get(session_id)
        if account is None:
            account = self.create_account(session_id, initial_balance)
        return account

    def remove_account(self, session_id: str) -> bool:
        """Remove an account.

        Args:
            session_id: Session ID

        Returns:
            True if removed, False if not found
        """
        if session_id in self._accounts:
            del self._accounts[session_id]
            return True
        return False

    def get_account_count(self) -> int:
        """Get the number of accounts.

        Returns:
            Number of accounts
        """
        return len(self._accounts)
