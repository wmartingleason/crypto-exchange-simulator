# Client-Side Network Management Implementation Guide

This document describes the implementation of robust client-side network management components, including heartbeat monitoring, rate limiting, sequence tracking, reconciliation, and REST fallback for data collection when WebSocket is unavailable.

## Overview

The client-side network management system provides:
- **Heartbeat Management**: Application-level PING/PONG to detect silent connections
- **Rate Limiting**: Proactive and reactive REST API rate limiting with exponential backoff
- **Sequence Tracking**: Detects missing packets using sequence IDs
- **Reconciliation**: Fetches missing data via REST when gaps are detected
- **REST Fallback**: Continuous data collection via REST when WebSocket is unavailable
- **Silent Connection Detection**: Detects when TCP connection is open but server stops sending

## Architecture

### Components

1. **NetworkManager** (`src/client/network/network_manager.py`)
   - Orchestrates all network components
   - Manages WebSocket lifecycle
   - Coordinates REST fallback when WS is unavailable

2. **HeartbeatManager** (`src/client/network/heartbeat.py`)
   - Sends periodic PING messages
   - Monitors PONG responses
   - Detects connection health issues

3. **RestRateLimiter** (`src/client/network/rate_limiter.py`)
   - Proactive rate limiting (sliding window)
   - Reactive rate limiting (exponential backoff on 429)
   - Wraps REST requests with retry logic

4. **SequenceTracker** (`src/client/network/sequence_tracker.py`)
   - Tracks expected sequence IDs per channel/symbol
   - Detects gaps in sequence numbers
   - Returns Gap objects for reconciliation

5. **Reconciler** (`src/client/network/reconciler.py`)
   - Fetches missing market data via REST
   - Fetches missing orders and balances
   - Handles price history requests

## Implementation Details

### 1. Heartbeat Management

**Purpose**: Detect silent connections where TCP is open but server stops sending data.

**Implementation**:

```python
class HeartbeatManager:
    def __init__(self, interval=60.0, timeout=10.0, on_health_change=None):
        self.interval = interval  # PING every 60 seconds
        self.timeout = timeout     # PONG timeout 10 seconds
        self.on_health_change = on_health_change  # Callback for health changes
    
    async def start(self, ws_connection):
        # Start heartbeat loop
        # Send PING every interval
        # Track pending PINGs
        # Check for PONG timeouts
    
    async def handle_pong(self, request_id):
        # Remove pending PING
        # Mark connection as healthy
    
    async def _check_pong_timeout(self, request_id):
        # If PONG not received within timeout, mark unhealthy
        # Trigger on_health_change(False)
```

**Key Points**:
- Sends PING messages every 60 seconds (configurable)
- Tracks pending PINGs with request IDs
- If PONG not received within 10 seconds, marks connection unhealthy
- Triggers callback to NetworkManager when health changes

### 2. Rate Limiting

**Purpose**: Prevent REST API overload and handle rate limit responses gracefully.

**Implementation**:

```python
class RestRateLimiter:
    def __init__(self, proactive=True, initial_backoff=1.0, max_backoff=60.0, backoff_multiplier=2.0):
        self.proactive = proactive  # Use sliding window tracking
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.backoff_multiplier = backoff_multiplier
        self._request_times = deque()  # Sliding window
        self._current_backoff = 0.0    # Current backoff delay
    
    async def retry_request(self, make_request, endpoint, max_retries=3):
        # Wraps REST requests
        # Tracks request rate proactively
        # Handles 429 responses with exponential backoff
        # Retries on rate limit errors
```

**Key Points**:
- Proactive: Tracks request rate using sliding window (e.g., max 10 requests per second)
- Reactive: On 429 response, applies exponential backoff
- Backoff starts at 1 second, doubles each time, max 60 seconds
- Automatically retries requests after backoff period

### 3. Sequence Tracking

**Purpose**: Detect missing packets by tracking sequence IDs in WebSocket messages.

**Implementation**:

```python
@dataclass
class Gap:
    channel: str
    symbol: str
    start_seq: int
    end_seq: int

class SequenceTracker:
    def update(self, channel: str, symbol: str, sequence_id: int) -> Optional[Gap]:
        # Track expected sequence ID per (channel, symbol) pair
        # If sequence_id > expected, return Gap object
        # If sequence_id == expected, update and return None
        # If sequence_id < expected, ignore (duplicate/out-of-order)
```

**Key Points**:
- Each MARKET_DATA message should include a `sequence_id` field
- Tracks expected sequence ID per (channel, symbol) combination
- Returns Gap object when gap detected (e.g., expected 3, received 5 → gap 3-4)
- Ignores duplicates and out-of-order messages

### 4. Reconciliation

**Purpose**: Fetch missing data via REST when sequence gaps are detected.

**Implementation**:

```python
class Reconciler:
    def __init__(self, base_url, session_id, rate_limiter, callbacks):
        # Callbacks for: market_data, price_history, orders, balance
    
    async def reconcile_market_data(self, symbol: str, gap: Gap):
        # Fetch missing market data for sequence gap
        # Uses REST API to get data for missing sequence IDs
    
    async def reconcile_price_history(self, symbol: str, start: datetime, end: datetime, limit: int):
        # Fetch historical price data via REST
        # Endpoint: GET /api/v1/prices?symbol=X&start=Y&end=Z&limit=N
        # Returns list of price points with timestamps
    
    async def reconcile_orders(self):
        # Fetch current orders via REST
    
    async def reconcile_balance(self):
        # Fetch current balance via REST
```

**Key Points**:
- Triggered automatically when SequenceTracker detects a gap
- Fetches missing data via REST API
- Price history endpoint: `/api/v1/prices` with query params
- Callbacks notify dashboard/client when data is reconciled

### 5. REST Fallback for Data Collection

**Purpose**: Continuously fetch data via REST when WebSocket is unavailable or not receiving messages.

**Implementation**:

```python
class NetworkManager:
    async def _handle_silent_connection(self):
        # Called when heartbeat detects silent connection
        # 1. Disconnect WebSocket
        # 2. Start REST data fetch loop
        # 3. Attempt to reconnect WebSocket
    
    async def _rest_data_fetch_loop(self):
        # Continuously fetch data via REST
        # Runs until WebSocket starts receiving messages again
        # Fetches every 2 seconds for all subscribed symbols
        # Stops automatically when WS resumes
    
    async def receive_ws_message(self):
        # When message received:
        # - Update _last_ws_message_time
        # - Stop REST fetch loop if running
```

**Key Behavior**:
- When WS stops receiving messages (detected by heartbeat or activity monitor):
  1. Disconnect the silent WebSocket connection
  2. Start continuous REST data fetching loop
  3. Attempt to reconnect WebSocket in background
- REST loop:
  - Fetches data every 2 seconds for all subscribed symbols
  - Uses `/api/v1/prices` endpoint with start/end timestamps
  - Continues even after WS reconnects (until messages are received)
  - Stops automatically when WS starts receiving messages
- Activity Monitor:
  - Checks `_last_ws_message_time` periodically
  - If idle > `ws_idle_timeout` (default 10s), treats as silent
  - Faster detection than heartbeat interval

### 6. Silent Connection Failure Mode

**Purpose**: Test client's ability to detect and handle silent connections.

**Server-Side Implementation** (`src/exchange_simulator/failures/strategies.py`):

```python
class SilentConnectionStrategy:
    def __init__(self, after_messages: int = 10):
        self.after_messages = after_messages
        self._session_counts: Dict[str, int] = {}  # Per-session tracking
    
    async def apply_outbound(self, message: dict, session_id: str) -> Optional[dict]:
        # Track message count per session
        count = self._session_counts.get(session_id, 0)
        count += 1
        self._session_counts[session_id] = count
        
        # After threshold, drop all outbound messages
        if count > self.after_messages:
            return None  # Drop message
        
        return message  # Allow message
```

**Configuration** (`src/exchange_simulator/config.py`):

```python
class FailuresConfig:
    silent_connection: Optional[FailureMode] = None

class FailureMode:
    enabled: bool = False
    after_messages: int = 10  # For silent connection
```

**Key Points**:
- **Per-session tracking**: Each WebSocket connection gets its own message count
- After N messages (configurable), server stops sending to that session
- TCP connection remains open, but no data is sent
- Client should detect via heartbeat timeout or activity monitor
- Client should disconnect, fetch data via REST, and reconnect

## Configuration

### Client Configuration (`src/client/config.py`)

```python
class NetworkConfig:
    heartbeat_interval: float = 60.0      # PING every 60s
    heartbeat_timeout: float = 10.0        # PONG timeout 10s
    ws_idle_timeout: float = 10.0          # Activity monitor timeout
    
    rate_limit_proactive: bool = True
    rate_limit_initial_backoff: float = 1.0
    rate_limit_max_backoff: float = 60.0
    rate_limit_backoff_multiplier: float = 2.0
    
    reconciliation_enabled: bool = True
    price_history_limit: int = 1000
    
    reconnect_initial_backoff: float = 1.0
    reconnect_max_backoff: float = 60.0
    reconnect_max_attempts: int = 10
```

## Integration with Dashboard

### Dashboard Updates (`src/client/dashboard.py`)

1. **Initialize NetworkManager**:
```python
self.network_manager = NetworkManager(
    base_url=base_url,
    session_id=self.session_id,
    config=self.config
)
```

2. **Set Callbacks**:
```python
self.network_manager.set_on_ws_message(self._handle_ws_message)
self.network_manager.set_on_reconciliation(self._handle_reconciliation)
```

3. **Handle Reconciliation Events**:
```python
def _handle_reconciliation(self, recon_type: str, data: Any):
    if recon_type == "price_history":
        # Process historical price data
        # Add to market data buffer
        # Add to candlestick aggregator
    elif recon_type == "market_data":
        # Process single market data point
    elif recon_type == "orders":
        # Update orders
    elif recon_type == "balance":
        # Update balance
```

## Server-Side Requirements

### REST API Endpoints

1. **Price History Endpoint** (`/api/v1/prices`):
   - Method: GET
   - Query params:
     - `symbol`: Trading symbol (e.g., "BTC/USD")
     - `start`: ISO timestamp (optional)
     - `end`: ISO timestamp (optional)
     - `limit`: Max number of points (optional)
   - Response:
     ```json
     {
       "prices": [
         {
           "timestamp": "2024-01-01T00:00:00Z",
           "price": 50000.0,
           "bid": 49999.0,
           "ask": 50001.0,
           "volume_24h": 1000.0
         }
       ]
     }
     ```

2. **Market Data Generator** (`src/exchange_simulator/market_data/generator.py`):
   - Must include `sequence_id` in MARKET_DATA messages
   - Must store price history in `_price_history` deque
   - Must implement `get_price_history()` method

## Testing

### Unit Tests

1. **HeartbeatManager** (`tests/unit/test_heartbeat.py`):
   - Test PING sending
   - Test PONG handling
   - Test timeout detection
   - Test health change callbacks

2. **SilentConnectionStrategy** (`tests/unit/test_silent_connection.py`):
   - Test per-session isolation
   - Test message dropping after threshold
   - Test session independence

3. **Integration** (`tests/unit/test_heartbeat_silent_connection.py`):
   - Test heartbeat detects silent connection
   - Test REST fallback activates
   - Test reconnection after silent period

## Flow Diagrams

### Silent Connection Detection and Recovery

```
1. WS Connected → Receiving Messages
2. Server Stops Sending (SilentConnectionStrategy)
3. Activity Monitor Detects Idle > 10s
   OR
   Heartbeat PING Times Out (> 10s)
4. NetworkManager._handle_silent_connection():
   a. Disconnect WS
   b. Start REST data fetch loop
   c. Attempt WS reconnect
5. REST Loop:
   - Fetches data every 2s
   - Continues until WS receives messages
6. WS Reconnects
7. WS Starts Receiving Messages
8. REST Loop Stops Automatically
9. Resume Normal WS Operation
```

### Sequence Gap Detection and Reconciliation

```
1. WS Receives MARKET_DATA with sequence_id=3
2. Next message has sequence_id=5
3. SequenceTracker detects gap (missing 4)
4. Reconciler.reconcile_market_data() triggered
5. REST API call to fetch missing data
6. Reconciled data sent to dashboard via callback
7. Dashboard updates market data buffer
```

## Error Handling

- **Network Errors**: Retry with exponential backoff
- **Rate Limiting**: Automatic backoff and retry
- **Invalid Data**: Log warning and skip
- **Connection Failures**: Automatic reconnection with backoff
- **Silent Connections**: Detect and switch to REST fallback

## Logging

All components should log:
- Connection events (connect, disconnect, reconnect)
- Heartbeat events (PING sent, PONG received, timeout)
- REST API calls (endpoint, params, response)
- Reconciliation events (gaps detected, data fetched)
- Rate limiting events (backoff applied, retries)

## Performance Considerations

- REST fetch interval: 2 seconds (configurable)
- Heartbeat interval: 60 seconds (configurable)
- Activity monitor check: Every 5 seconds (half of idle timeout)
- Rate limit window: Sliding window (e.g., 10 requests/second)
- Price history limit: 1000 points per request (configurable)

## Future Enhancements

- Adaptive fetch interval based on data rate
- Compression for historical data
- Batch reconciliation for multiple symbols
- Metrics and monitoring integration
- Circuit breaker pattern for REST failures

