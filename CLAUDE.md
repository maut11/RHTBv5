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
- `self.position_ledger = PositionLedger(POSITION_LEDGER_DB)` (line 124)
- Passed to `ChannelHandlerManager` for parser injection (line 135)
- Passed to all parser constructors via `ChannelHandlerManager.update_handlers()` (line 92)
- Initial sync in `on_ready()` via `sync_from_robinhood()` (lines 179-188)
- Periodic sync task `_ledger_sync_task()` every `LEDGER_SYNC_INTERVAL` seconds (lines 343-371)
- Expired lock cleanup during sync (line 364)

**trade_executor.py**:
- Receives `position_ledger` in `__init__` (line 200)
- On trim/exit: `resolve_position()` fills missing contract details (lines 342-361)
- On buy success: `record_buy()` updates ledger (lines 501-506)
- On sell success: `record_sell()` updates ledger (lines 606-615)

### Configuration Values

From `config.py` (lines 149-152):
- `POSITION_LEDGER_DB = "logs/position_ledger.db"` - Database file path
- `LEDGER_SYNC_INTERVAL = 60` - Robinhood reconciliation interval (seconds)
- `LEDGER_HEURISTIC_STRATEGY = "fifo"` - Default resolution heuristic
- `LEDGER_LOCK_TIMEOUT = 60` - Lock timeout for pending exits (seconds)

---

## OpenAI Parsing System Architecture

The trading bot uses OpenAI's API to parse Discord trading alerts into structured JSON for execution.

### Alert Types and Schemas

Four Pydantic schemas define valid alert structures (see `channels/base_parser.py` lines 100-196):

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

Implementation: `channels/base_parser.py` lines 292-400

### Response Caching

Duplicate messages are cached to avoid redundant API calls:
- TTL: 5 minutes
- Key: Normalized message content + message history context
- Location: `channels/base_parser.py` `ParseCache` class (lines 15-96)

### Parser Constructor and Position Ledger Injection

`BaseParser.__init__` (line 223) accepts an optional `position_ledger` parameter, stored as `self.position_ledger`. This allows parsers to query open positions for prompt context. The ledger is passed through the `ChannelHandlerManager` (line 73), which receives it during construction (line 135) and forwards it to every parser via keyword argument (line 92). Parsers that do not use it simply store `None`. The `SeanParser` constructor accepts `**kwargs` for forward compatibility (line 6-7 of `channels/sean.py`).

### Message Context Handling

When parsing a message, the system provides context to improve accuracy:

1. **Message history**: Recent messages from the channel, configurable per channel via `message_history_limit` in `CHANNELS_CONFIG` (default 5, FiFi uses 10). See `main.py` line 555 for the per-channel lookup and lines 533-569 for the full message handling flow.
2. **Reply context**: Original message included when parsing a reply
3. **Forward detection**: Forwarded messages are detected and parsed appropriately (see `main.py` lines 646-671)

### Date Parsing

The LLM directly converts dates to YYYY-MM-DD format. Prompt instructions in `channels/sean.py` and `channels/fifi.py` specify:
- 0DTE becomes today's date
- Dates without year use smart year detection (future = current year, passed = next year)
- Monthly expirations (e.g., "JAN 2026") resolve to third Friday

Fallback Python parsing exists in `base_parser.py` for edge cases.

### Message Edits

When a message is edited:
- Edit is logged with original and edited content
- **No trade action is taken** to prevent duplicate executions
- Notification sent to commands webhook

Implementation: `main.py` lines 575-630

---

## Channel Parsers

The bot supports multiple channel parsers, each tailored to a specific trader's messaging style. All parsers extend `BaseParser` (`channels/base_parser.py`) and override `build_prompt()` at minimum. Two active parsers exist: `SeanParser` and `FiFiParser`.

### SeanParser (`channels/sean.py`)

The original parser for Sean's technical analysis alerts. Overrides only `build_prompt()` and uses the base `_normalize_entry()` for date fallback. Constructor accepts `**kwargs` for forward compatibility with the position ledger parameter.

### FiFiParser (`channels/fifi.py`)

Parses FiFi's (sauced2002) conversational, non-standardized Discord trading alerts. Deployed in tracking-only mode (`min_trade_contracts=0`).

**Enhancements over base parsing** (five total):

1. **Position ledger injection** -- Queries `self.position_ledger.get_open_positions()` and injects compact JSON (ticker, strike, type, exp, avg_cost, qty) into the prompt so the LLM can resolve ambiguous trims/exits. Implemented in `_get_open_positions_json()` (lines 29-47).

2. **Reply context with clear tags** -- Uses `PRIMARY:` / `REPLYING TO:` labels instead of Sean's `PRIMARY MESSAGE:` / `ORIGINAL MESSAGE:` pattern. Critical for FiFi's reply-based trims where the reply contains only a price.

3. **Time delta message history** -- Reformats the `[HH:MM:SS]` timestamps from `get_channel_message_history()` into relative `[Xm ago]` deltas. Uses 10 messages instead of 5 (via `message_history_limit: 10` in config). Implemented in `_format_history_with_deltas()` (lines 49-80).

4. **Negative constraint firewall** -- Explicit "Do NOT" rules at the top of the prompt to prevent false positives on watchlists, conditional setups, bare tickers, correction fragments, recaps, and target prices.

5. **Role ping signal** -- Detects FiFi's alert role ping (`<@&1369304547356311564>`) in the message and passes `has_alert_ping: true/false` to the prompt as a signal of actionability.

**Custom `_normalize_entry()` post-processing** (lines 260-305):
- Stop-out phrase detection (forces action to "exit" with "market" price)
- Embedded contract notation regex (e.g., "BMNR50p" to ticker/strike/type)
- Size normalization mapping (e.g., "1/4" to "half", "tiny" to "lotto")
- Default 0DTE for buys without expiration
- Ticker cleanup (uppercase, strip `$`)

**Prompt features**:
- Multi-trade detection instructions for messages containing multiple distinct trades
- 10+ few-shot examples covering buy (explicit/implicit/lotto/multi), trim (reply-based/typo), exit (standard/stopped), and null (conditional/watchlist/intent/fragment/bare ticker)
- Price parsing rule: "from $X" is entry price context, not current price

### CHANNELS_CONFIG

Channel configuration in `config.py` (lines 106-142). Each entry maps a channel name to parser class, channel IDs, risk parameters, and model settings.

| Channel | Parser | Live Trading | Message History | Key Differences |
|---------|--------|-------------|-----------------|-----------------|
| Sean | `SeanParser` | Yes (`min_trade_contracts=2`) | 5 (default) | Standard prompt, no position injection |
| FiFi | `FiFiParser` | No (`min_trade_contracts=0`, tracking-only) | 10 | Position injection, time deltas, negative constraints, role ping |

The `message_history_limit` config key controls how many recent messages are fetched for context per channel (see `main.py` line 555). Channels without this key default to 5.

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

Commands are handled in `main.py` within the `EnhancedDiscordClient._handle_command()` method (lines 760-881). Each command dispatches to a dedicated handler method:

- `_handle_get_price()` - AI-powered contract parsing via `PriceParser`, fetches market data from Robinhood API
- `_handle_pnl_command()` - Queries `EnhancedPerformanceTracker` for trade history and calculates metrics
- `_handle_positions_command()` - Fetches positions from Robinhood, calculates real-time P&L using market data
- `_handle_portfolio_command()` - Retrieves portfolio value and buying power from `RobinhoodTrader`

### Price Command Response Fields

The `!price` command displays comprehensive option data:

**Price Data**: Mark, bid, ask, spread, previous close, price change (dollar and percent)

**Greeks**: Delta, Gamma, Theta, Vega, Rho

**Market Data**: Volume, open interest, implied volatility (IV)

Implementation: `main.py` lines 1152-1251
