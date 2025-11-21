"""Client configuration."""

from pydantic import BaseModel, Field


class NetworkConfig(BaseModel):
    """Network management configuration."""

    heartbeat_interval: float = Field(
        default=60.0, description="PING interval in seconds"
    )
    heartbeat_timeout: float = Field(
        default=10.0, description="PONG timeout in seconds"
    )
    rate_limit_proactive: bool = Field(
        default=True, description="Enable proactive rate limiting"
    )
    rate_limit_initial_backoff: float = Field(
        default=1.0, description="Initial backoff delay in seconds"
    )
    rate_limit_max_backoff: float = Field(
        default=60.0, description="Maximum backoff delay in seconds"
    )
    rate_limit_backoff_multiplier: float = Field(
        default=2.0, description="Backoff multiplier for exponential backoff"
    )
    reconciliation_enabled: bool = Field(
        default=True, description="Enable automatic reconciliation"
    )
    reconnect_initial_backoff: float = Field(
        default=1.0, description="Initial backoff before reconnect attempts"
    )
    reconnect_max_backoff: float = Field(
        default=10.0, description="Maximum reconnect backoff"
    )
    reconnect_max_attempts: int = Field(
        default=5, description="Maximum reconnect attempts before giving up"
    )
    price_history_limit: int = Field(
        default=500,
        description="Maximum number of price history points to request per reconciliation",
    )
    ws_idle_timeout: float = Field(
        default=10.0,
        description="Seconds without WS messages before declaring connection silent",
    )


class ClientConfig(BaseModel):
    """Client configuration."""

    network: NetworkConfig = Field(default_factory=NetworkConfig)

