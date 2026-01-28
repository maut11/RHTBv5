---
name: m-implement-ai-logging-system
branch: feature/ai-logging-system
status: pending
created: 2026-01-28
---

# Implement AI-Readable Logging System

## Problem/Goal
The current logging system uses plain text format which is difficult for AI analysis. We need a comprehensive logging system that:
1. Uses JSON Lines (JSONL) format for machine-readable logs
2. Daily rotating log files (e.g., `bot_2026-01-28.log`)
3. Captures all bot activity for AI-assisted debugging and analysis
4. Auto-cleans old logs (14-day retention)

## Success Criteria
- [ ] Create `ai_logging.py` module with JSONFormatter and DailyRotatingJSONHandler
- [ ] Daily rotating log files named `bot_YYYY-MM-DD.log`
- [ ] 14-day retention with automatic cleanup
- [ ] Logs capture: Discord events, OpenAI parsing, trade execution, errors with stack traces
- [ ] Structured `extra` data support for context-rich logging
- [ ] Replace current `setup_comprehensive_logging()` in main.py
- [ ] Bot runs successfully with new logging system
- [ ] Log format is AI-parseable (valid JSON per line)

## Context Manifest
<!-- Added by context-gathering agent -->

### How the Current Logging System Works

The trading bot currently uses Python's standard `logging` module with a multi-tier approach. When `main.py` starts, it calls `setup_comprehensive_logging()` (lines 77-135) which creates the primary logging infrastructure. This function creates a `logs/` directory if it does not exist, then configures the `main` logger with three handlers:

1. **debug_handler**: Writes to `logs/debug.log` at DEBUG level with timestamps
2. **error_handler**: Writes to `logs/errors.log` at ERROR level only
3. **console_handler**: Outputs INFO+ level to stdout with simplified format

The system also configures the root logger to catch all module logs, and crucially redirects `sys.stdout` and `sys.stderr` through `LoggingPrintRedirect` class (lines 45-75), which captures all `print()` statements and routes them to the logger. This means every print statement in the codebase ends up in `debug.log`.

The current plain-text log format is:
```
%(asctime)s - %(name)s - %(levelname)s - %(message)s
```
with datetime format `%Y-%m-%d %H:%M:%S`.

**The Problem**: These logs are human-readable but difficult for AI analysis. They lack structured data, use inconsistent formats across different event types, and have no machine-parseable fields for extracting metrics.

### Where Logging Currently Happens

**1. Discord Events (main.py)**
- `on_ready()` (line 244): Logs connection success, channel handler updates
- `on_message()` (line 399): Logs incoming messages from monitored channels
- `on_message_edit()` (line 436): Logs message edits with before/after content
- `on_disconnect()` (line 322): Logs disconnections with count
- `on_resumed()` (line 269): Logs reconnection events

**2. OpenAI Parsing (channels/base_parser.py)**
- `_call_openai_with_retry()` (lines 291-341): Logs API calls, retries, latency, token usage
- `parse_message()` (lines 424-519): Logs parsing results, cache hits, validation status
- `_log_parsed_actions()` (lines 411-422): Logs raw action extraction from OpenAI responses

**3. Trade Execution (trade_executor.py)**
- `_blocking_handle_trade()` (lines 274-593): Logs trade processing steps, symbol mapping, fallback lookups
- `_execute_buy_order()` (lines 672-800): Logs position sizing calculations, order placement, validation
- `_execute_sell_order()` (lines 802-978): Logs market data fetch, price calculation, order results
- `_send_trade_alert()` (lines 1048-1065): Logs alert queueing

**4. Broker Communication (trader.py)**
- `login()` (lines 50-130): Logs authentication attempts and results
- `place_option_buy_order()` (lines 684-745): Logs order placement details
- `place_option_sell_order()` (lines 747-863): Logs sell orders with price sources
- `get_option_market_data()` (lines 1092-1109): Logs market data retrieval

**5. Alert System (alert_manager.py)**
- `_process_alerts()` (lines 312-357): Logs alert processing, successes, failures
- `_send_alert_with_retry()` (lines 359-377): Logs retry attempts and circuit breaker state
- `_watchdog_monitor()` (lines 412-446): Logs processor health checks

**6. Performance Tracking (performance_tracker.py)**
- `record_entry()` (lines 233-299): Logs trade entries with channel attribution
- `record_trim()` (lines 337-416): Logs partial exits with P&L data
- `record_exit()` (lines 422-533): Logs full exits with final P&L calculation

### Existing Daily Rotation Infrastructure

The file `daily_log_rotation.py` contains a partial implementation that the new system can build upon or replace:

```python
class DailyRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    def __init__(self, log_dir, log_type, retention_days=30):
        # Creates files named: {YYYY-MM-DD}_{log_type}.log
        # Uses midnight rotation with cleanup of old files
```

This existing handler uses `TimedRotatingFileHandler` with `when='midnight'` and implements `_cleanup_old_logs()` that deletes files older than `retention_days`. However, it outputs plain text, not JSONL.

### What Events Need JSON Logging

Based on code analysis, the new AI-readable logging system must capture these structured events:

**Discord Events:**
```json
{
  "timestamp": "2026-01-28T14:30:00.000Z",
  "event_type": "discord_message",
  "channel_id": 1072555808832888945,
  "channel_name": "Sean",
  "message_id": "123456789",
  "content_preview": "SPY 580c 0dte @ 1.50",
  "has_embeds": false,
  "is_reply": false,
  "is_forward": false
}
```

**OpenAI Parsing Events:**
```json
{
  "timestamp": "2026-01-28T14:30:00.500Z",
  "event_type": "openai_parse",
  "channel_name": "Sean",
  "model": "gpt-4o-mini",
  "latency_ms": 450.5,
  "token_usage": {"prompt": 850, "completion": 45, "total": 895},
  "cache_hit": false,
  "parsed_action": "buy",
  "parsed_ticker": "SPY",
  "parsed_strike": 580,
  "parsed_type": "call",
  "parsed_expiration": "2026-01-28",
  "parsed_price": 1.50,
  "validation_passed": true
}
```

**Trade Execution Events:**
```json
{
  "timestamp": "2026-01-28T14:30:01.200Z",
  "event_type": "trade_execution",
  "action": "buy",
  "channel_name": "Sean",
  "trader_symbol": "SPY",
  "broker_symbol": "SPY",
  "strike": 580,
  "option_type": "call",
  "expiration": "2026-01-28",
  "quantity": 5,
  "limit_price": 1.53,
  "order_id": "abc123",
  "execution_time_ms": 234,
  "success": true,
  "sim_mode": false,
  "size_calculation": {
    "portfolio_value": 100000,
    "allocation_pct": 10,
    "max_dollar_amount": 10000,
    "final_contracts": 5
  }
}
```

**Error Events:**
```json
{
  "timestamp": "2026-01-28T14:30:05.000Z",
  "event_type": "error",
  "severity": "ERROR",
  "component": "trader",
  "error_type": "ConnectionError",
  "message": "Failed to connect to Robinhood API",
  "stack_trace": "Traceback (most recent call last)...",
  "context": {
    "symbol": "SPY",
    "operation": "place_option_buy_order"
  }
}
```

### Integration Points for New Logging

The new `ai_logging.py` module needs to integrate at these locations:

**1. Replace `setup_comprehensive_logging()` in main.py (line 138)**
```python
# Current:
logger = setup_comprehensive_logging()

# Should become:
from ai_logging import setup_ai_logging
logger = setup_ai_logging()
```

**2. Add structured logging calls in base_parser.py**
The `_call_openai_with_retry()` method returns `(content, latency, token_info)` - this data needs to be captured in JSONL format.

**3. Add structured logging in trade_executor.py**
The `_execute_buy_order()` and `_execute_sell_order()` methods need to emit structured events after order placement.

**4. Preserve print statement capture**
The `LoggingPrintRedirect` pattern should continue to work, converting print statements to log entries (which will then be formatted as JSON).

### Configuration Requirements

From `config.py`, the logging configuration block (lines 139-149):
```python
LOGGING_CONFIG = {
    "log_level": "DEBUG",
    "max_log_size_mb": 100,
    "backup_count": 5,
    "log_format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "channels_to_log": ["ALL"],
    "log_trade_details": True,
    "log_parsing_attempts": True,
    "log_performance_updates": True
}
```

The new system should respect these settings while adding:
- JSONL output format
- Daily rotation with `bot_YYYY-MM-DD.log` naming
- 14-day retention (configurable)
- Structured `extra` data support

### Technical Reference Details

#### Component Interfaces & Signatures

**Current main.py logging setup:**
```python
def setup_comprehensive_logging() -> logging.Logger:
    """Setup comprehensive logging that captures everything"""
    # Returns configured 'main' logger
```

**New ai_logging.py should provide:**
```python
class JSONFormatter(logging.Formatter):
    """Custom formatter that outputs JSON Lines format"""
    def format(self, record: logging.LogRecord) -> str:
        # Convert record to JSON with extra fields support
        pass

class DailyRotatingJSONHandler(logging.handlers.TimedRotatingFileHandler):
    """Handler that rotates daily with JSONL output"""
    def __init__(self, log_dir: str = "logs", retention_days: int = 14):
        # Creates: logs/bot_YYYY-MM-DD.log
        pass

    def doRollover(self):
        # Override to use bot_YYYY-MM-DD.log naming
        pass

    def _cleanup_old_logs(self):
        # Delete logs older than retention_days
        pass

def setup_ai_logging(log_dir: str = "logs", retention_days: int = 14) -> logging.Logger:
    """Setup AI-readable logging system"""
    # Returns configured logger with JSONL output
    pass

def log_event(event_type: str, **kwargs):
    """Convenience function for structured event logging"""
    # Logs event with automatic timestamp and structure
    pass
```

#### Data Structures

**Log file naming pattern:**
```
logs/bot_2026-01-28.log
logs/bot_2026-01-27.log
logs/bot_2026-01-26.log
...
```

**JSONL format (one JSON object per line):**
```
{"timestamp":"2026-01-28T14:30:00.000Z","event_type":"startup","version":"v4"}
{"timestamp":"2026-01-28T14:30:01.000Z","event_type":"discord_message","channel":"Sean","content":"..."}
{"timestamp":"2026-01-28T14:30:02.000Z","event_type":"openai_parse","latency_ms":450,"action":"buy"}
```

#### File Locations

- **New module location**: `/Users/mautasimhussain/trading-bots/RHTBv5/ai_logging.py`
- **Integration point**: `/Users/mautasimhussain/trading-bots/RHTBv5/main.py` (line 138)
- **Log output directory**: `/Users/mautasimhussain/trading-bots/RHTBv5/logs/`
- **Configuration**: `/Users/mautasimhussain/trading-bots/RHTBv5/config.py` (add new settings if needed)
- **Existing rotation reference**: `/Users/mautasimhussain/trading-bots/RHTBv5/daily_log_rotation.py`

### Patterns to Follow

**1. Extra fields in logging (used in trading_logger.py):**
```python
# Current pattern for structured data
structured_message = f"[{event_type.upper()}] {message}"
if data:
    structured_message += f" | Data: {json.dumps(data, default=str)}"
```

**2. TimedRotatingFileHandler usage (from daily_log_rotation.py):**
```python
super().__init__(
    filename=str(log_filename),
    when='midnight',
    interval=1,
    backupCount=retention_days,
    encoding='utf-8'
)
```

**3. Print redirection (from main.py LoggingPrintRedirect):**
The new system must preserve this pattern so existing `print()` statements continue to be captured.

### Backward Compatibility Requirements

1. **Existing code uses `print()` extensively** - the JSONL logger must continue to capture these via stdout redirection
2. **Multiple modules use `logging.getLogger(name)`** - the root logger configuration affects them all
3. **Console output should remain human-readable** - the JSONL format is for file output only
4. **Existing `logs/` directory structure** - can coexist with new `bot_YYYY-MM-DD.log` files

## User Notes
- Goal is to enable "analyze today's logs for errors" workflow
- Must capture: messages received, parsing requests/responses, trades, all errors
- Gemini recommended JSONL format with Python's logging + TimedRotatingFileHandler

## Work Log
<!-- Updated as work progresses -->
- [2026-01-28] Task created based on Gemini recommendations for AI-readable logging
