# Additional Guidance

@sessions/CLAUDE.sessions.md

This file provides instructions for Claude Code for working in the cc-sessions framework.

## Position Ledger System

The trading bot uses a SQLite-backed position ledger (`position_ledger.py`) for persistent position tracking, enabling resolution of generic alerts like "Trim SPY" to specific contracts.

### Core Components

**PositionLedger class** (`position_ledger.py`):
- SQLite database at `logs/position_ledger.db`
- CCID (Canonical Contract ID) format: `{TICKER}_{YYYYMMDD}_{STRIKE}_{C/P}` (e.g., `SPY_20260128_595_C`)
- Lot-level tracking for position averaging
- Thread-safe with `threading.Lock`

**Database Tables**:
- `positions` - Main position tracking (ccid, ticker, strike, option_type, expiration, total_quantity, avg_cost_basis, status)
- `position_lots` - Individual lot entries for averaging (lot_id, ccid, quantity, cost_basis, entry_time)

### Key Methods

- `record_buy(trade_data)` - Creates new position or averages into existing
- `record_sell(ccid, quantity, price)` - Records trim or full exit with FIFO lot allocation
- `resolve_position(ticker, hints, heuristic)` - Resolves ticker to specific position using weighted matching
- `sync_from_robinhood(trader)` - Reconciles local state with Robinhood API
- `lock_for_exit(ccid)` / `unlock_position(ccid)` - Prevents concurrent sell attempts

### Position Resolution Heuristics

When multiple positions exist for the same ticker, the system uses weighted scoring and configurable heuristics:

**Scoring weights** (from hints):
- Exact strike match: +10 points
- Exact expiry match: +10 points
- Option type match: +5 points
- 0DTE bonus: +3 points

**Heuristics** (`config.py: LEDGER_HEURISTIC_STRATEGY`):
- `fifo` - First In First Out (oldest entry, default)
- `nearest` - Nearest expiration (0DTE priority)
- `profit` - Highest unrealized profit (requires market data)
- `largest` - Largest position by quantity

### Integration Points

**main.py**:
- `self.position_ledger = PositionLedger(POSITION_LEDGER_DB)` (line 121)
- Initial sync in `on_ready()` via `sync_from_robinhood()` (lines 174-184)
- Periodic sync task `_ledger_sync_task()` every `LEDGER_SYNC_INTERVAL` seconds (lines 333-361)
- Expired lock cleanup during sync (line 354)

**trade_executor.py**:
- Receives `position_ledger` in `__init__` (line 200)
- On trim/exit: `resolve_position()` fills missing contract details (lines 342-361)
- On buy success: `record_buy()` updates ledger (lines 501-506)
- On sell success: `record_sell()` updates ledger (lines 606-615)

### Configuration Values

From `config.py` (lines 109-113):
- `POSITION_LEDGER_DB = "logs/position_ledger.db"` - Database file path
- `LEDGER_SYNC_INTERVAL = 60` - Robinhood reconciliation interval (seconds)
- `LEDGER_HEURISTIC_STRATEGY = "fifo"` - Default resolution heuristic
- `LEDGER_LOCK_TIMEOUT = 60` - Lock timeout for pending exits (seconds)

---

## OpenAI Parsing System Architecture

The trading bot uses OpenAI's API to parse Discord trading alerts into structured JSON for execution.

### Alert Types and Schemas

Four Pydantic schemas define valid alert structures (see `channels/base_parser.py` lines 100-195):

- **BuyAlert**: New position entries - requires ticker, strike, type, expiration, price, size
- **TrimAlert**: Partial exits - requires ticker, price; other fields optional (resolved from active positions)
- **ExitAlert**: Full position closes - requires ticker, price; other fields optional
- **CommentaryAlert**: Non-actionable messages - action="null"

### Model Strategy and Reliability

The system uses a tiered approach for reliability and speed:

1. **Primary model**: gpt-4o-mini (faster, cheaper)
2. **Fallback model**: gpt-4o (more accurate for complex messages)
3. **JSON mode**: Always enabled via `response_format: {"type": "json_object"}`
4. **Retry logic**: Exponential backoff (1s, 2s, 4s) for transient errors

Implementation: `channels/base_parser.py` lines 291-399

### Response Caching

Duplicate messages are cached to avoid redundant API calls:
- TTL: 5 minutes
- Key: Normalized message content + message history context
- Location: `channels/base_parser.py` `ParseCache` class (lines 15-96)

### Message Context Handling

When parsing a message, the system provides context to improve accuracy:

1. **Message history**: Last 5 messages from the channel (see `main.py` lines 523-566)
2. **Reply context**: Original message included when parsing a reply
3. **Forward detection**: Forwarded messages are detected and parsed appropriately (see `main.py` lines 457-521)

### Date Parsing

The LLM directly converts dates to YYYY-MM-DD format. Prompt instructions in `channels/sean.py` specify:
- 0DTE becomes today's date
- Dates without year use smart year detection (future = current year, passed = next year)
- Monthly expirations (e.g., "JAN 2026") resolve to third Friday

Fallback Python parsing exists in `base_parser.py` for edge cases.

### Message Edits

When a message is edited:
- Edit is logged with original and edited content
- **No trade action is taken** to prevent duplicate executions
- Notification sent to commands webhook

Implementation: `main.py` lines 400-455

---

## Discord Bot Commands

The bot provides Discord commands for account monitoring, trading information, and system diagnostics. Commands are sent to the configured commands channel and responses are delivered via webhook.

### Trading Commands

| Command | Description |
|---------|-------------|
| `!price <query>` | Option price lookup with full Greeks, IV, and price change. Accepts natural language queries (e.g., `!price SPY 600c 1/31`). Alias: `!getprice` |
| `!pnl [days]` | P&L summary for the last N days (default 30). Shows total P&L, win rate, trade count, best/worst trade, average hold time |
| `!positions` | Open positions with entry price, current price, and P&L per position. Includes total portfolio P&L |
| `!portfolio` | Account summary showing portfolio value and buying power |
| `!trades` | Recent completed trades with P&L percentages |
| `!mintick <symbol>` | Get minimum tick size for a symbol (useful for SPX 0DTE) |
| `!clear <channel>` | Clear fallback position history for a channel |

### System Commands

| Command | Description |
|---------|-------------|
| `!status` | System status overview (mode, channels, connection status) |
| `!heartbeat` | Detailed health check with recent trade activity |
| `!sim on\|off` | Toggle simulation mode |
| `!testing on\|off` | Toggle testing channel mode |

### Alert System Commands

| Command | Description |
|---------|-------------|
| `!alert_health` | Alert system diagnostics (processor status, circuit breaker) |
| `!alert_restart` | Force restart alert processors |
| `!alert_test` | Send test notification |
| `!queue` | Alert queue status and metrics |
| `!help` | Display all available commands |

### Command Implementation

Commands are handled in `main.py` within the `EnhancedDiscordClient.handle_command()` method (lines 752-874). Each command dispatches to a dedicated handler method:

- `_handle_get_price()` - AI-powered contract parsing via `PriceParser`, fetches market data from Robinhood API
- `_handle_pnl_command()` - Queries `EnhancedPerformanceTracker` for trade history and calculates metrics
- `_handle_positions_command()` - Fetches positions from Robinhood, calculates real-time P&L using market data
- `_handle_portfolio_command()` - Retrieves portfolio value and buying power from `RobinhoodTrader`

### Price Command Response Fields

The `!price` command displays comprehensive option data:

**Price Data**: Mark, bid, ask, spread, previous close, price change (dollar and percent)

**Greeks**: Delta, Gamma, Theta, Vega, Rho

**Market Data**: Volume, open interest, implied volatility (IV)

Implementation: `main.py` lines 1145-1244
