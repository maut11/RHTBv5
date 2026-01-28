---
name: h-implement-trading-logic-overhaul
branch: feature/trading-logic-overhaul
status: pending
created: 2026-01-28
---

# Trading Logic Overhaul - Merge Best of Both Systems

## Problem/Goal

Merge the robust trading logic from the old bot with RHTBv5's improved position management. The old bot had superior execution patterns (cascade selling, fill validation, break-even stops) while RHTBv5 has better position tracking (SQLite ledger, weighted heuristics, thread safety).

**Key improvements to implement:**

1. **Position State Machine** - Add explicit states: `opening → open → trimmed → closed`
2. **Fill Validation Gate** - Prevent trim/exit on unfilled orders
3. **Cascade Sell Mechanism** - Patient (60s) for trims, urgent (30s) for exits
4. **Break-Even Stop After Trim** - Protect remaining contracts at entry price
5. **Async Fill Monitoring** - Background task polling order status
6. **Tighter Risk Parameters** - -30% stop (vs -50%), 25% trim (vs 50%), min 2 / max 20 contracts

## Success Criteria

**Position State Machine:**
- [ ] Position ledger schema includes `status` field with states: opening, open, trimmed, closed, cancelled
- [ ] Buy orders create positions in "opening" status
- [ ] Positions transition to "open" only after fill confirmation

**Fill Validation:**
- [ ] Trim/exit operations reject positions in "opening" status with clear error message
- [ ] Fill monitoring background task polls order status every 10 seconds
- [ ] Orders timeout and cancel after 10 minutes if unfilled

**Cascade Sell Mechanism:**
- [ ] `cascade_sell_trim()` implemented with 60-second intervals (mark → midpoint → bid → bid×0.97)
- [ ] `cascade_sell_exit()` implemented with 30-second intervals (mark → bid → bid×0.97 → bid×0.95)
- [ ] Each cascade step fetches fresh market prices

**Break-Even Stop:**
- [ ] After successful trim, stop loss is placed at entry price (break-even)
- [ ] Existing stop loss is cancelled before trim execution

**Risk Parameters:**
- [ ] Stop loss default changed to -30% (from -50%)
- [ ] Stop loss delay changed to 5 minutes (from 15)
- [ ] Trim percentage changed to 25% (from 50%)
- [ ] Contract limits enforced: min 2, max 20

**Integration:**
- [ ] All existing tests pass
- [ ] Bot successfully executes buy → trim → exit cycle with new logic

## Context Manifest
<!-- Added by context-gathering agent -->

### How Position State Management Currently Works

The current RHTBv5 system uses a **dual position tracking architecture**: a SQLite-backed `PositionLedger` (in `/Users/mautasimhussain/trading-bots/RHTBv5/position_ledger.py`) and a JSON-backed `PositionManager` (in `/Users/mautasimhussain/trading-bots/RHTBv5/position_manager.py`). Both track positions, but with different purposes.

**Position Ledger (SQLite) - Primary Source of Truth:**

The `PositionLedger` class maintains positions in SQLite at `logs/position_ledger.db`. The schema currently supports these fields for positions:

```python
# positions table schema (lines 156-174)
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ccid TEXT NOT NULL UNIQUE,           # Canonical Contract ID (e.g., SPY_20260128_595_C)
    ticker TEXT NOT NULL,
    strike REAL NOT NULL,
    option_type TEXT NOT NULL,
    expiration TEXT NOT NULL,
    total_quantity INTEGER NOT NULL DEFAULT 0,
    avg_cost_basis REAL,
    status TEXT NOT NULL DEFAULT 'open',  # CURRENT VALUES: 'open', 'closed', 'pending_exit'
    pending_exit_since TEXT,
    channel TEXT,
    first_entry_time TEXT NOT NULL,
    last_update_time TEXT NOT NULL,
    notes TEXT,
    UNIQUE(ticker, expiration, strike, option_type)
)
```

**CRITICAL GAP:** The current `status` field supports only `'open'`, `'closed'`, and `'pending_exit'`. The task requires adding `'opening'` and `'trimmed'` states to implement the full state machine: `opening -> open -> trimmed -> closed`.

The `Position` dataclass (lines 51-69) represents position records:
```python
@dataclass
class Position:
    ccid: str
    ticker: str
    strike: float
    option_type: str
    expiration: str
    total_quantity: int
    avg_cost_basis: float
    status: str                # Currently just 'open', 'closed', 'pending_exit'
    channel: Optional[str]
    first_entry_time: str
    last_update_time: str
    pending_exit_since: Optional[str] = None
    notes: Optional[str] = None
```

**Position Manager (JSON) - Transient Tracking:**

The `EnhancedPositionManager` (`/Users/mautasimhussain/trading-bots/RHTBv5/position_manager.py`) stores positions in `tracked_contracts_live.json` for quick lookups during trading. It has a `status` field that supports `'open'` and `'closed'` (lines 119-120):

```python
contract_info = {
    "trade_id": trade_id,
    "symbol": trader_symbol,
    "trader_symbol": trader_symbol,
    "broker_symbol": broker_symbol,
    # ... other fields
    "status": "open"  # Set on creation
}
```

### How Order Execution Currently Works

**Buy Order Flow (trade_executor.py lines 720-848):**

When a buy signal is received, `_execute_buy_order()` follows this sequence:

1. **Price Calculation** - Applies channel-specific padding (default 2.5%) and rounds to tick size
2. **Position Sizing** - Calculates contracts based on portfolio value, MAX_PCT_PORTFOLIO (10%), size multipliers, and channel multiplier
3. **Validation** - Calls `trader.validate_order_requirements()` to check buying power and contract existence
4. **Order Placement** - Calls `trader.place_option_buy_order()` which uses `robin_stocks.robinhood.order_buy_option_limit()`
5. **Stop Loss Scheduling** - If successful, schedules a delayed stop loss via `DelayedStopLossManager.schedule_stop_loss()` (default 15 minutes, 50% stop)
6. **Recording** - Calls `performance_tracker.record_entry()` and `position_manager.add_position()` and `position_ledger.record_buy()`

**CRITICAL GAP:** The current flow does NOT create positions in "opening" status. The `position_ledger.record_buy()` method (lines 266-345) immediately sets status to `'open'`:
```python
# Line 330 - Creates new position with 'open' status
cursor.execute('''
    INSERT INTO positions
    (ccid, ticker, strike, option_type, expiration, total_quantity,
     avg_cost_basis, status, channel, first_entry_time, last_update_time)
    VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
    # ... status hardcoded to 'open' ^^^
''')
```

**Sell Order Flow (trade_executor.py lines 850-1026):**

The `_execute_sell_order()` method handles trims/exits:

1. **Position Lookup** - Gets current position from Robinhood via `trader.get_open_option_positions()` and `trader.find_open_option_position()`
2. **Quantity Calculation** - For trims: `sell_quantity = max(1, total_quantity // 2)`. For exits: `sell_quantity = total_quantity`
3. **Order Cancellation** - Pre-cancels existing orders via `trader.cancel_open_option_orders()`
4. **Price Discovery** - Fetches market data and calculates price: `mark -> midpoint -> bid` priority
5. **Order Placement** - Uses `trader.place_option_sell_order_with_timeout_retry()` which has 3-retry logic with progressive pricing
6. **Fill Monitoring** - For trim orders, waits for confirmation via `trader.wait_for_order_confirmation()` (max 180 seconds)
7. **Trailing Stop** - If trim confirmed, places trailing stop via `_handle_trailing_stop()`

**CRITICAL GAP:** The current sell logic does NOT implement cascade selling. It places ONE order and retries with price adjustments if rejected, but doesn't wait with timed intervals as the old bot did.

### How Stop Loss Management Currently Works

**DelayedStopLossManager (trade_executor.py lines 161-194):**

```python
class DelayedStopLossManager:
    def __init__(self):
        self.pending_stops = {}

    def schedule_stop_loss(self, trade_id: str, stop_data: dict, delay_seconds: int = 900):
        """Schedule a stop loss to be placed after delay"""
        def place_stop_after_delay():
            time.sleep(delay_seconds)  # Currently 15 minutes (900 seconds)
            # ... places stop loss order
```

The stop is scheduled with `STOP_LOSS_DELAY_SECONDS = 900` (15 minutes) from `config.py` line 18.

**Stop Loss Placement (trader.py lines 1055-1090):**

```python
def place_option_stop_loss_order(self, symbol, strike, expiration, opt_type, quantity, stop_price):
    # Uses stop-limit order type
    result = r.order_sell_option_stop_limit(
        positionEffect='close',
        creditOrDebit='credit',
        limitPrice=rounded_stop_price,
        stopPrice=rounded_stop_price,
        symbol=broker_symbol,
        quantity=quantity,
        expirationDate=expiration,
        strike=strike,
        optionType=opt_type,
        timeInForce='gtc'  # Good Till Cancelled
    )
```

**Trailing Stop Logic (trade_executor.py lines 1028-1094):**

The `_handle_trailing_stop()` method is called after successful trims:

```python
def _handle_trailing_stop(self, trader, trade_obj, config, active_position, log_func, is_sim_mode):
    # ...
    # Calculate trailing stop price
    trailing_stop_pct = config.get("trailing_stop_loss_pct", 0.20)  # 20% default
    trailing_stop_candidate = current_market_price * (1 - trailing_stop_pct)
    new_stop_price = max(trailing_stop_candidate, purchase_price)  # Floor at entry price
```

**CRITICAL GAP:** The current trailing stop uses `max(trailing_stop_candidate, purchase_price)` which is essentially a break-even stop, BUT it's calculated from trailing stop percentage rather than explicitly setting to entry price. The task requires explicit break-even stop placement at entry price after trim.

### Current Risk Parameters (config.py)

```python
# Lines 2-5
MAX_PCT_PORTFOLIO = 0.10           # 10% of portfolio per trade
MAX_DOLLAR_AMOUNT = 25000          # Hard cap
MIN_TRADE_QUANTITY = 1             # Minimum contracts

# Lines 18-20
STOP_LOSS_DELAY_SECONDS = 900      # 15 minutes (task requires 5 minutes = 300)
DEFAULT_INITIAL_STOP_LOSS = 0.50   # 50% loss protection (task requires -30%)
DEFAULT_TRAILING_STOP_PCT = 0.20   # 20% trailing stop

# Channel config (lines 85-102)
CHANNELS_CONFIG = {
    "Sean": {
        "initial_stop_loss": 0.50,        # Task requires 0.30
        "trailing_stop_loss_pct": 0.20,
        # ... no min/max contract limits defined
    }
}
```

**GAPS:**
- No `min_contracts` or `max_contracts` enforcement (task requires min 2, max 20)
- Stop loss at 50% not 30%
- Stop loss delay at 15 minutes not 5 minutes
- Trim percentage not configurable (hardcoded to 50% in `_execute_sell_order`)

### Price Fetching and Tick Rounding

**Market Data Fetching (trader.py lines 1092-1109):**

```python
def get_option_market_data(self, symbol, expiration, strike, opt_type):
    broker_symbol = self.normalize_symbol_for_broker(symbol)
    data = r.get_option_market_data(broker_symbol, expiration, strike, opt_type)
    return data
```

The market data returns a structure like:
```python
[{
    'bid_price': '1.50',
    'ask_price': '1.55',
    'mark_price': '1.52',
    'high_fill_rate_buy_price': '...',
    'high_fill_rate_sell_price': '...',
    # ... other fields
}]
```

**Tick Rounding (trader.py lines 595-635):**

```python
def round_to_tick(self, price: float, symbol: str, round_up_for_buy: bool = False, expiration: str = None):
    tick_size = self.get_instrument_tick_size_with_expiration(symbol, expiration)

    if round_up_for_buy:
        ticks = math.ceil(price / tick_size)
    else:
        ticks = round(price / tick_size)

    rounded_price = ticks * tick_size
    return round(rounded_price, 2)
```

For cascade selling, each price step will need fresh market data and proper tick rounding.

### Background Task Management (main.py)

The bot uses asyncio for background tasks:

```python
# Line 267-331: Heartbeat task
async def _heartbeat_task(self):
    while True:
        await asyncio.sleep(1800)  # Every 30 minutes
        # ... send heartbeat

# Line 333-361: Ledger sync task
async def _ledger_sync_task(self):
    while True:
        await asyncio.sleep(LEDGER_SYNC_INTERVAL)  # Every 60 seconds
        # ... sync with Robinhood
```

**For Fill Monitoring Background Task:** A similar pattern should be used:
```python
async def _fill_monitoring_task(self):
    while True:
        await asyncio.sleep(10)  # Poll every 10 seconds
        # Check unfilled orders, timeout after 10 minutes
```

### Order Fill Monitoring (Current Implementation)

**trader.py lines 1111-1180:**

```python
def wait_for_order_confirmation(self, order_id: str, max_wait_seconds: int = 300) -> dict:
    check_intervals = [2, 5, 10, 15, 20, 30, 30, 60]  # Progressive intervals

    for interval in check_intervals:
        time.sleep(interval)
        order_info = self.get_option_order_info(order_id)

        if order_info.get('state') == 'filled':
            return {"status": "filled", ...}
        elif order_info.get('state') in ['cancelled', 'rejected', 'failed']:
            return {"status": order_state, ...}

    return {"status": "timeout", ...}
```

**trade_executor.py lines 676-718:**

```python
def _monitor_order_fill(self, trader, order_id, max_wait_time=600):
    check_intervals = [5, 10, 15, 20, 30, 30, 60, 60, 60, 60, 70, 80, 100]

    for interval in check_intervals:
        time.sleep(interval)
        order_info = trader.get_option_order_info(order_id)

        if order_info.get('state') == 'filled':
            return True, elapsed_time
        elif order_info.get('state') in ['cancelled', 'rejected', 'failed']:
            return False, elapsed_time

    # Cancel order if timeout
    trader.cancel_option_order(order_id)
    return False, elapsed_time
```

**CRITICAL GAP:** These monitoring functions are synchronous and blocking. The task requires an async background task that polls every 10 seconds and handles multiple pending orders.

### What Cascade Sell Implementation Needs

The cascade sell mechanism should:

1. **For Trims (Patient - 60s intervals):**
   - Step 1: Place sell at mark price
   - Wait 60s, check if filled
   - Step 2: Place sell at midpoint (bid+ask)/2
   - Wait 60s, check if filled
   - Step 3: Place sell at bid price
   - Wait 60s, check if filled
   - Step 4: Place sell at bid * 0.97 (3% below bid)

2. **For Exits (Urgent - 30s intervals):**
   - Step 1: Place sell at mark price
   - Wait 30s, check if filled
   - Step 2: Place sell at bid price
   - Wait 30s, check if filled
   - Step 3: Place sell at bid * 0.97
   - Wait 30s, check if filled
   - Step 4: Place sell at bid * 0.95 (5% below bid)

Each step needs to:
- Cancel previous unfilled order
- Fetch fresh market prices
- Round to valid tick size
- Place new limit order
- Monitor for fill

### Technical Reference Details

#### Files to Modify

| File | Changes Required |
|------|------------------|
| `/Users/mautasimhussain/trading-bots/RHTBv5/position_ledger.py` | Add 'opening' and 'trimmed' status values; add method to transition states |
| `/Users/mautasimhussain/trading-bots/RHTBv5/trade_executor.py` | Implement `cascade_sell_trim()`, `cascade_sell_exit()`, modify `_execute_buy_order()` for opening status, modify `_handle_trailing_stop()` for break-even |
| `/Users/mautasimhussain/trading-bots/RHTBv5/config.py` | Update `STOP_LOSS_DELAY_SECONDS` to 300, `DEFAULT_INITIAL_STOP_LOSS` to 0.30, add `MIN_CONTRACTS=2`, `MAX_CONTRACTS=20`, `TRIM_PERCENTAGE=0.25` |
| `/Users/mautasimhussain/trading-bots/RHTBv5/trader.py` | No major changes needed - existing methods support cascade pattern |
| `/Users/mautasimhussain/trading-bots/RHTBv5/main.py` | Add fill monitoring background task |

#### Key Method Signatures

**Position Ledger - New Methods:**
```python
def create_opening_position(self, trade_data: dict) -> str:
    """Create position in 'opening' status"""

def transition_to_open(self, ccid: str) -> bool:
    """Transition position from 'opening' to 'open' after fill confirmation"""

def transition_to_trimmed(self, ccid: str) -> bool:
    """Transition position from 'open' to 'trimmed' after partial exit"""

def cancel_opening_position(self, ccid: str) -> bool:
    """Mark unfilled 'opening' position as 'cancelled'"""
```

**Trade Executor - New Methods:**
```python
async def cascade_sell_trim(self, trader, trade_obj, config, log_func) -> Tuple[bool, str]:
    """Patient cascade sell for trims - 60s intervals, mark->midpoint->bid->bid*0.97"""

async def cascade_sell_exit(self, trader, trade_obj, config, log_func) -> Tuple[bool, str]:
    """Urgent cascade sell for exits - 30s intervals, mark->bid->bid*0.97->bid*0.95"""

def place_breakeven_stop(self, trader, trade_obj, entry_price: float) -> bool:
    """Place stop loss at exact entry price after successful trim"""
```

**Main.py - New Background Task:**
```python
async def _fill_monitoring_task(self):
    """Poll order status every 10s, timeout and cancel after 10 min"""
    while True:
        await asyncio.sleep(10)
        # Get all 'opening' positions from ledger
        # Check order status for each
        # Transition to 'open' if filled
        # Cancel and mark 'cancelled' if timeout (10 min)
```

#### Data Structures

**Cascade Step Configuration:**
```python
TRIM_CASCADE_STEPS = [
    {'price_type': 'mark', 'multiplier': 1.0, 'wait_seconds': 60},
    {'price_type': 'midpoint', 'multiplier': 1.0, 'wait_seconds': 60},
    {'price_type': 'bid', 'multiplier': 1.0, 'wait_seconds': 60},
    {'price_type': 'bid', 'multiplier': 0.97, 'wait_seconds': 0},  # Final step
]

EXIT_CASCADE_STEPS = [
    {'price_type': 'mark', 'multiplier': 1.0, 'wait_seconds': 30},
    {'price_type': 'bid', 'multiplier': 1.0, 'wait_seconds': 30},
    {'price_type': 'bid', 'multiplier': 0.97, 'wait_seconds': 30},
    {'price_type': 'bid', 'multiplier': 0.95, 'wait_seconds': 0},  # Final step
]
```

#### Configuration Updates

```python
# config.py additions
STOP_LOSS_DELAY_SECONDS = 300     # 5 minutes (changed from 900)
DEFAULT_INITIAL_STOP_LOSS = 0.30  # 30% (changed from 0.50)
MIN_CONTRACTS = 2                  # Minimum contracts per trade
MAX_CONTRACTS = 20                 # Maximum contracts per trade
TRIM_PERCENTAGE = 0.25             # Trim 25% of position (not 50%)
FILL_MONITORING_INTERVAL = 10      # Seconds between fill checks
FILL_TIMEOUT_SECONDS = 600         # 10 minute timeout for unfilled orders
```

#### Order States to Track

For fill monitoring, track these Robinhood order states:
- `'queued'` - Order submitted, waiting
- `'unconfirmed'` - Order being processed
- `'confirmed'` - Order accepted by exchange
- `'partially_filled'` - Some contracts filled
- `'filled'` - All contracts filled (SUCCESS)
- `'cancelled'` - Order cancelled
- `'rejected'` - Order rejected by exchange
- `'failed'` - Order failed

#### Integration Points

1. **Buy Flow Integration:**
   - Modify `_execute_buy_order()` to create position in 'opening' status BEFORE placing order
   - Store order_id in position record for tracking
   - Let background task handle fill monitoring and state transition

2. **Trim/Exit Flow Integration:**
   - Check position status before allowing trim/exit (reject if 'opening')
   - Cancel existing stop loss before cascade sell
   - After successful cascade, place break-even stop (trim) or nothing (exit)
   - Update position status to 'trimmed' or 'closed'

3. **Stop Loss Flow Integration:**
   - After successful trim, cancel any existing stops
   - Place new stop at entry price (break-even)
   - Use GTC (Good Till Cancelled) order type

## User Notes
<!-- Any specific notes or requirements from the developer -->

**Old Bot Reference Summary:**
- Fill monitoring: Poll every 10s, timeout 10 min
- Stop loss: 5 min delay, -30% from entry, GTC orders
- Trim: 25% of position, cascade 60s intervals
- Exit: 100% of position, cascade 30s intervals
- Cascade pricing: mark → midpoint → bid → bid×0.97
- Contract limits: min 2, max 20
- Break-even stop placed after successful trim

## Work Log
<!-- Updated as work progresses -->
- [2026-01-28] Task created from trading logic comparison discussion
