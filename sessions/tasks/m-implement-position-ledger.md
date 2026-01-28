---
name: m-implement-position-ledger
branch: feature/position-ledger
status: pending
created: 2026-01-28
---

# Implement Persistent Position Ledger

## Problem/Goal
The trading bot lacks persistent memory of open positions. When generic alerts like "Trim SPY" or "Exit TSLA" arrive, the bot doesn't know which specific contracts are held. This causes:
- Inability to handle ticker-only trim/exit commands
- No position state after restarts
- Redundant API calls to check positions
- No cost basis tracking for P&L
- Ambiguity when multiple contracts exist for same ticker

Build a persistent SQLite-backed position ledger that:
1. Tracks all open positions with full contract details
2. Syncs with Robinhood API for ground truth reconciliation
3. Resolves generic "Trim $TICKER" alerts to specific contracts using heuristics
4. Supports position averaging with lot-level tracking
5. Enables pre-flight validation before trade execution

## Success Criteria
- [ ] Create `position_ledger.py` with SQLite-backed storage
- [ ] Schema with CCID (Canonical Contract ID): `{TICKER}_{EXPIRY}_{STRIKE}_{TYPE}`
- [ ] Sync from Robinhood: `sync_from_robinhood()` using `get_open_option_positions()`
- [ ] Alert hint extraction: Parse strike, expiry, type, qty hints from alerts
- [ ] Weighted matching: Score positions by hint matches, fallback to heuristic
- [ ] Heuristics: FIFO (default), nearest-expiry (0dte priority), profit-first
- [ ] Pre-flight validator: Block trades for non-existent positions
- [ ] Lock mechanism: `pending_exit` status prevents double-sells
- [ ] Integrate with `trade_executor.py`: ledger updates on buy/sell
- [ ] Handle "Exit all $TICKER": close multiple positions
- [ ] Handle averaging: lot-level tracking when adding to position
- [ ] Periodic reconciliation (startup + 60s interval)

## Context Manifest
<!-- Added by context-gathering agent -->

### How Position Handling Currently Works

The trading bot currently tracks positions through THREE separate systems that do NOT share state efficiently, leading to the core problem this task addresses:

**1. Robinhood API (Ground Truth):**
When `trader.py`'s `get_open_option_positions()` is called, it invokes `r.get_open_option_positions()` from robin_stocks. The Robinhood API returns a list of position dictionaries, each containing:
```python
{
    'chain_symbol': 'SPY',      # The broker symbol (e.g., 'SPXW' for SPX options)
    'option': 'https://api.robinhood.com/options/instruments/UUID/',  # URL to instrument
    'quantity': '5.0000',       # String representation of quantity
    'average_price': '1.5000',  # Entry price as string
    # ... other fields
}
```

To get contract details (strike, expiry, type), a SECOND API call is required via `get_option_instrument_data(url)` which fetches the instrument URL and returns:
```python
{
    'strike_price': '595.0000',
    'expiration_date': '2026-01-28',
    'type': 'call',
    # ... other fields
}
```

This two-call pattern is expensive (latency + rate limits) and is currently performed on EVERY trim/exit alert in `trade_executor.py` at lines 858-864:
```python
all_positions = trader.get_open_option_positions()
position = trader.find_open_option_position(all_positions, symbol, strike, expiration, opt_type)
```

**2. JSON Position Manager (`position_manager.py`):**
The `EnhancedPositionManager` class maintains a JSON file (`tracked_contracts_live.json`) that stores positions keyed by channel_id. Each position record looks like:
```python
{
    "trade_id": "trade_1769560139524",
    "symbol": "OPEN",
    "trader_symbol": "OPEN",
    "broker_symbol": "OPEN",
    "symbol_variants": ["OPEN"],
    "strike": 11,
    "type": "call",
    "expiration": "2026-11-21",
    "purchase_price": 1.4,
    "entry_price": 1.4,
    "size": "half",
    "quantity": 35,
    "channel": "Sean",
    "created_at": "2026-01-28T00:28:59.667946+00:00",
    "status": "open"  # Can be: open, trimmed, closed
}
```

This manager is initialized in `main.py` line 117:
```python
self.position_manager = EnhancedPositionManager("tracked_contracts_live.json")
```

The `find_position()` method (lines 145-207) searches by trade_id first, then by symbol variants, returning the most recent open position. Symbol mapping via `get_all_symbol_variants()` handles SPX/SPXW equivalency.

**3. SQLite Performance Tracker (`performance_tracker.py`):**
The `EnhancedPerformanceTracker` maintains a SQLite database (`logs/performance_tracking.db`) with trades table containing:
```sql
CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    trade_id TEXT UNIQUE NOT NULL,
    channel TEXT NOT NULL,
    channel_id INTEGER,
    ticker TEXT NOT NULL,
    strike REAL NOT NULL,
    option_type TEXT NOT NULL,
    expiration TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT,
    entry_price REAL NOT NULL,
    exit_price REAL,
    quantity INTEGER NOT NULL,
    quantity_remaining INTEGER DEFAULT 0,
    size_category TEXT NOT NULL,
    pnl_dollars REAL,
    pnl_percent REAL,
    status TEXT NOT NULL DEFAULT 'open',  -- open, partially_trimmed, closed, stop_loss, cleared
    ...
)
```

The `find_open_trade_by_ticker()` method (lines 301-335) searches for open trades by ticker and optional channel, returning the trade_id.

### The Core Problem: Generic Alerts

When an alert like "Trim SPY" arrives without contract details, the current flow in `trade_executor.py` `_blocking_handle_trade()` (lines 335-406):

1. Parses message via OpenAI - gets `{action: "trim", ticker: "SPY"}` with no strike/expiry/type
2. Tries `position_manager.find_position()` - may find wrong contract if multiple SPY positions
3. Tries `performance_tracker.find_open_trade_by_ticker()` as fallback
4. If still incomplete, tries CSV feedback log `get_recent_parse_for_channel()`
5. Final fallback: `robinhood_positions.get_contract_info_for_ticker()` - expensive API call

Even after all fallbacks, if multiple contracts exist for the same ticker (e.g., SPY 595C and SPY 600P both open), the system has NO intelligent heuristic to select the correct one. It just returns the most recent.

### Trade Execution Flow (Where Ledger Updates Should Occur)

**BUY Order Flow (`_execute_buy_order`, lines 672-800):**
```
1. Calculate position size based on portfolio value and config multipliers
2. Get optimal price from market data or alert
3. Round to tick size (handles SPX 0DTE special cases)
4. Validate order requirements (buying power, contract existence)
5. Place order via trader.place_option_buy_order()
6. If successful:
   - Generate trade_id: f"trade_{int(datetime.now().timestamp() * 1000)}"
   - Schedule delayed stop loss (15 min via DelayedStopLossManager)
   - Record entry: performance_tracker.record_entry(trade_obj)
   - Add position: position_manager.add_position(channel_id, trade_obj)
   - Send alert async
```
**INTEGRATION POINT**: After successful buy order (line 468-471), add `ledger.record_buy(...)`.

**SELL Order Flow (`_execute_sell_order`, lines 802-978):**
```
1. Get current position quantity from Robinhood API
2. Calculate sell quantity (half for trim, all for exit)
3. Cancel any existing orders for contract
4. Get market price (mark > midpoint > bid)
5. Apply sell padding and round to tick
6. Place order via trader.place_option_sell_order_with_timeout_retry()
7. For trim: wait for confirmation before placing trailing stop
8. If successful:
   - Record trim: performance_tracker.record_trim(trade_id, trim_data)
   - Handle trailing stop
   - OR record exit: performance_tracker.record_exit(trade_id, exit_data)
   - Clear position: position_manager.clear_position(channel_id, trade_id)
```
**INTEGRATION POINT**: Before sell execution (line 858), query ledger for position. After successful sell (line 970), update ledger.

### Alert Parsing and Hint Extraction

The `base_parser.py` defines Pydantic schemas for alerts:

**BuyAlert** (lines 100-108): Requires all fields
```python
class BuyAlert(BaseModel):
    action: Literal["buy"]
    ticker: str
    strike: float
    type: Literal["call", "put"]
    expiration: str  # YYYY-MM-DD
    price: float
    size: Literal["full", "half", "lotto"] = "full"
```

**TrimAlert** (lines 127-153): Only ticker required, others optional
```python
class TrimAlert(BaseModel):
    action: Literal["trim"]
    ticker: str
    strike: Optional[float] = None
    type: Optional[Literal["call", "put"]] = None
    expiration: Optional[str] = None
    price: Union[float, Literal["BE"]]
```

The OpenAI prompt (built by channel-specific parsers like `SeanParser`) extracts structured data. When contract details are present in the alert text (e.g., "Trim SPY 595c 1/28 @ $2.50"), OpenAI should return them. The task should enhance this to extract **hints** even when incomplete (e.g., "Trim the calls" could set type="call" hint).

The `_standardize_action()` method (lines 241-282) normalizes action variations:
- buy, entry, bto, long -> "buy"
- trim, scale, partial -> "trim"
- exit, close, stop, sell -> "exit"

### Symbol Mapping System

`config.py` defines mappings (lines 26-73):
```python
SYMBOL_MAPPINGS = {"SPX": "SPXW"}  # What traders say -> What broker uses
REVERSE_SYMBOL_MAPPINGS = {"SPXW": "SPX"}  # Auto-generated inverse

def get_broker_symbol(symbol: str) -> str  # SPX -> SPXW
def get_trader_symbol(broker_symbol: str) -> str  # SPXW -> SPX
def get_all_symbol_variants(symbol: str) -> list  # ["SPX", "SPXW"]
```

**Critical for ledger**: When storing positions, store the normalized ticker. When matching alerts, use `get_all_symbol_variants()` to match any variant.

### Existing State Files and Their Formats

**`tracked_contracts_live.json`** (current position manager):
```json
{
  "1398211580470235176": [  // channel_id as string key
    {
      "trade_id": "trade_1769560139524",
      "symbol": "OPEN",
      "trader_symbol": "OPEN",
      "broker_symbol": "OPEN",
      "symbol_variants": ["OPEN"],
      "strike": 11,
      "type": "call",
      "expiration": "2026-11-21",
      "purchase_price": 1.4,
      "entry_price": 1.4,
      "size": "half",
      "quantity": 35,
      "channel": "Sean",
      "created_at": "2026-01-28T00:28:59+00:00",
      "status": "open"
    }
  ]
}
```

**`logs/performance_tracking.db`** (SQLite):
- `trades` table with full trade lifecycle
- `trade_events` table for entry/trim/exit events
- `performance_summary` table for daily aggregates

### Proposed Position Ledger Design

**CCID (Canonical Contract ID) Format:**
```
{TICKER}_{EXPIRY}_{STRIKE}_{TYPE}
Example: SPY_20260128_595_C
```
This provides a unique, human-readable identifier for each contract.

**SQLite Schema for `position_ledger.db`:**
```sql
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ccid TEXT NOT NULL UNIQUE,           -- SPY_20260128_595_C
    ticker TEXT NOT NULL,                -- SPY (normalized, not SPXW)
    strike REAL NOT NULL,
    option_type TEXT NOT NULL,           -- call/put
    expiration TEXT NOT NULL,            -- YYYY-MM-DD

    -- Quantity tracking
    total_quantity INTEGER NOT NULL DEFAULT 0,
    avg_cost_basis REAL,

    -- Status
    status TEXT NOT NULL DEFAULT 'open', -- open, pending_exit, closed
    pending_exit_since TEXT,             -- ISO timestamp when locked

    -- Metadata
    channel TEXT,
    first_entry_time TEXT NOT NULL,
    last_update_time TEXT NOT NULL,
    notes TEXT,

    -- Indexes for fast lookup
    UNIQUE(ticker, expiration, strike, option_type)
);

CREATE TABLE position_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ccid TEXT NOT NULL,
    lot_id TEXT NOT NULL UNIQUE,         -- lot_1769560139524
    quantity INTEGER NOT NULL,
    cost_basis REAL NOT NULL,
    entry_time TEXT NOT NULL,
    source_trade_id TEXT,                -- Links to performance_tracker
    status TEXT NOT NULL DEFAULT 'open', -- open, sold
    exit_time TEXT,
    exit_price REAL,

    FOREIGN KEY (ccid) REFERENCES positions(ccid)
);

CREATE INDEX idx_positions_ticker ON positions(ticker);
CREATE INDEX idx_positions_status ON positions(status);
CREATE INDEX idx_lots_ccid ON position_lots(ccid);
```

**Key Methods for `PositionLedger` class:**

```python
class PositionLedger:
    def __init__(self, db_path: str = "logs/position_ledger.db"):
        # Initialize SQLite connection

    def sync_from_robinhood(self, trader) -> SyncResult:
        """Reconcile local state with Robinhood API ground truth"""

    def record_buy(self, trade_data: dict) -> str:
        """Add or average into position, returns ccid"""

    def resolve_position(self, ticker: str, hints: dict = None) -> Optional[Position]:
        """
        Resolve ticker to specific contract using hints and heuristics.
        hints = {strike: 595, type: 'call', expiry: '2026-01-28', qty: 2}
        Heuristics: FIFO, nearest-expiry (0DTE priority), profit-first
        """

    def lock_for_exit(self, ccid: str) -> bool:
        """Set pending_exit status to prevent double-sells"""

    def record_sell(self, ccid: str, quantity: int, price: float) -> bool:
        """Record partial or full exit"""

    def get_open_positions(self, ticker: str = None) -> List[Position]:
        """Get all open positions, optionally filtered by ticker"""
```

### Integration Points Summary

| Location | Current Code | Ledger Integration |
|----------|-------------|-------------------|
| `main.py` L117 | `self.position_manager = EnhancedPositionManager(...)` | Add `self.position_ledger = PositionLedger()` |
| `main.py` on_ready | - | Add `await loop.run_in_executor(None, self.position_ledger.sync_from_robinhood, self.live_trader)` |
| `trade_executor.py` L133 | `__init__` receives position_manager | Add position_ledger parameter |
| `trade_executor.py` L468-471 | After buy success | Add `self.position_ledger.record_buy(trade_obj)` |
| `trade_executor.py` L357-360 | Before sell, find position | Replace with `position = self.position_ledger.resolve_position(ticker, hints)` |
| `trade_executor.py` L858 | Get position from RH API | Query ledger first, RH API only for validation |
| `trade_executor.py` L970 | After sell success | Add `self.position_ledger.record_sell(ccid, qty, price)` |

### Technical Reference Details

#### Key Function Signatures

**From `trader.py`:**
```python
def get_open_option_positions(self) -> List[dict]
def find_open_option_position(self, all_positions, symbol, strike, expiration, opt_type) -> Optional[dict]
def get_option_instrument_data(self, url: str) -> Optional[dict]
def get_option_market_data(self, symbol, expiration, strike, opt_type) -> List[dict]
```

**From `position_manager.py`:**
```python
def add_position(self, channel_id: int, trade_data: dict) -> Optional[dict]
def find_position(self, channel_id: int, trade_data: dict) -> Optional[dict]
def clear_position(self, channel_id: int, trade_id: str) -> bool
def get_open_positions(self, channel_id: int = None) -> List[dict]
```

**From `performance_tracker.py`:**
```python
def record_entry(self, trade_data: dict) -> str  # Returns trade_id
def record_trim(self, trade_id: str, trim_data: dict) -> Optional[TradeRecord]
def record_exit(self, trade_id: str, exit_data: dict) -> Optional[TradeRecord]
def find_open_trade_by_ticker(self, ticker: str, channel: str = None) -> Optional[str]
```

**From `config.py`:**
```python
def get_broker_symbol(symbol: str) -> str
def get_trader_symbol(broker_symbol: str) -> str
def get_all_symbol_variants(symbol: str) -> list
```

#### Data Structures Expected

**trade_data dict (passed to record_buy/record_entry):**
```python
{
    'trade_id': 'trade_1769560139524',
    'ticker': 'SPY',
    'trader_symbol': 'SPY',
    'broker_symbol': 'SPY',
    'strike': 595.0,
    'type': 'call',
    'expiration': '2026-01-28',
    'price': 1.50,
    'quantity': 5,
    'size': 'full',
    'channel': 'Sean',
    'channel_id': 1072555808832888945
}
```

**Robinhood position dict (from get_open_option_positions):**
```python
{
    'chain_symbol': 'SPY',
    'option': 'https://api.robinhood.com/options/instruments/UUID/',
    'quantity': '5.0000',
    'average_price': '1.5000',
    'trader_symbol': 'SPY',  # Added by trader.py
    'broker_symbol': 'SPY'   # Added by trader.py
}
```

**Instrument data dict (from get_option_instrument_data):**
```python
{
    'strike_price': '595.0000',
    'expiration_date': '2026-01-28',
    'type': 'call'
}
```

#### Configuration Values

From `config.py`:
```python
PERFORMANCE_DB_FILE = "logs/performance_tracking.db"
STOP_LOSS_DELAY_SECONDS = 900  # 15 minutes
```

Suggested for ledger:
```python
POSITION_LEDGER_DB = "logs/position_ledger.db"
LEDGER_SYNC_INTERVAL = 60  # Reconcile with RH every 60 seconds
```

#### File Locations

- **New position ledger**: `/Users/mautasimhussain/trading-bots/RHTBv5/position_ledger.py`
- **Database location**: `/Users/mautasimhussain/trading-bots/RHTBv5/logs/position_ledger.db`
- **Integration in trade_executor**: `/Users/mautasimhussain/trading-bots/RHTBv5/trade_executor.py`
- **Integration in main**: `/Users/mautasimhussain/trading-bots/RHTBv5/main.py`
- **Symbol mapping config**: `/Users/mautasimhussain/trading-bots/RHTBv5/config.py`

## User Notes
- Goal: Enable "Trim SPY" to automatically resolve to correct contract(s)
- Handle multiple contracts same ticker with FIFO/profit-first/nearest-expiry strategies
- Support position averaging with per-lot tracking
- Reconcile with Robinhood on startup and periodically
- Reduce redundant API calls via local state

## Work Log
<!-- Updated as work progresses -->
- [2026-01-28] Task created based on Gemini brainstorm session
