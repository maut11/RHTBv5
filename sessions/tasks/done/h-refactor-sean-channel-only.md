---
name: h-refactor-sean-channel-only
branch: feature/sean-channel-only
status: complete
created: 2026-01-27
completed: 2026-01-27
---

# Refactor Trading Bot to Sean Channel Only

## Problem/Goal
The trading bot currently supports multiple Discord trading channels (Sean, Ryan, Eva, Will, FiFi). The user wants to simplify the codebase to only support Sean channel trading, removing all other channel-specific code and configurations.

## Success Criteria
- [x] Remove all non-Sean channel parser files (eva.py, fifi.py, ryan.py, will.py)
- [x] Update config.py to only include Sean channel configuration
- [x] Remove non-Sean channel imports from main.py
- [x] Remove Ryan-specific logic from trade_executor.py
- [x] Bot starts successfully with only Sean channel support
- [x] Sean channel alerts are processed correctly (test with simulation mode)

## Context Manifest
<!-- Added by context-gathering agent -->

### How the Multi-Channel Trading System Currently Works

The trading bot is a Discord-based automated options trading system that listens to multiple Discord channels from different traders (Sean, Ryan, Eva, Will, FiFi), parses their trade alerts using OpenAI, and executes the corresponding trades via the Robinhood API using the `robin_stocks` library.

**Message Flow - From Discord to Trade Execution:**

When a Discord message arrives, the flow begins in `main.py` within the `EnhancedDiscordClient.on_message()` method. The client checks if the message's channel ID matches any configured channel in `CHANNELS_CONFIG`. If a match is found, the appropriate channel handler (parser) is retrieved via `ChannelHandlerManager.get_handler(channel_id)`. The handler manager builds handlers dynamically at startup based on the `CHANNELS_CONFIG` dictionary in `config.py`.

The `ChannelHandlerManager` class (lines 164-190 in `main.py`) iterates through `CHANNELS_CONFIG`, instantiates the appropriate parser class using `globals()[parser_class_name]`, and maps channel IDs to parser instances:

```python
def update_handlers(self, testing_mode: bool):
    self.handlers.clear()
    for name, config in CHANNELS_CONFIG.items():
        parser_class_name = config.get("parser")
        if parser_class_name in globals():
            parser_class = globals()[parser_class_name]
            channel_id = config.get("test_id") if testing_mode else config.get("live_id")
            if channel_id:
                parser_instance = parser_class(self.openai_client, channel_id, {**config, "name": name})
                self.handlers[channel_id] = parser_instance
```

The channel parsers all inherit from `BaseParser` (`channels/base_parser.py`), which provides common functionality for OpenAI API calls, JSON parsing, action standardization, and date handling. Each channel parser overrides `build_prompt()` to provide trader-specific parsing instructions and may override `_normalize_entry()` for channel-specific post-processing.

**Parser Imports in main.py (Lines 22-28):**
```python
from channels.sean import SeanParser
from channels.will import WillParser
from channels.eva import EvaParser
from channels.ryan import RyanParser
from channels.fifi import FiFiParser
from channels.price_parser import PriceParser
```

These imports are critical - removing the non-Sean imports will cause the `ChannelHandlerManager` to skip those channels since `globals()[parser_class_name]` will fail to find the classes.

**CHANNELS_CONFIG Structure (config.py Lines 85-178):**

The `CHANNELS_CONFIG` dictionary defines all channel configurations with the following structure:
```python
CHANNELS_CONFIG = {
    "Ryan": {
        "live_id": 1072559822366576780,
        "test_id": 1396011198343811102,
        "parser": "RyanParser",
        "multiplier": 1.0,
        "min_trade_contracts": 1,
        "initial_stop_loss": 0.5,
        # ... other settings
    },
    "Eva": { ... },
    "Sean": {
        "live_id": 1072555808832888945,
        "test_id": 1398211580470235176,
        "parser": "SeanParser",
        "multiplier": 1.0,
        "min_trade_contracts": 1,
        "initial_stop_loss": 0.50,
        "trailing_stop_loss_pct": 0.20,
        "buy_padding": 0.025,
        "sell_padding": 0.01,
        "model": "gpt-4o-2024-08-06",
        "color": 3066993,  # Green
        "description": "Sean's technical analysis based trades",
        "risk_level": "medium-high",
        "typical_hold_time": "1-4 hours",
        "trade_first_mode": True
    },
    "Will": { ... },
    "FiFi": { ... }
}
```

To simplify to Sean-only, the entire `CHANNELS_CONFIG` dictionary should be reduced to only contain the "Sean" entry. The configuration values for Sean should be preserved exactly.

### Ryan-Specific Logic in trade_executor.py

The `trade_executor.py` file contains special logic for Ryan's channel that needs to be removed. This logic is found in the `_blocking_handle_trade` method (lines 416-428):

```python
if action == "buy":
    # ========== NON-SEQUENTIAL TRADE DETECTION (RYAN'S CHANNEL) ==========
    if handler.name == "Ryan":
        # Check for existing open positions for Ryan's channel
        existing_trades = self.performance_tracker.get_open_trades_for_channel(handler.name)
        if existing_trades and len(existing_trades) > 0:
            log_func(f"WARNING: Ryan non-sequential trade detected: {len(existing_trades)} open position(s) exist")
            print(f"EXISTING POSITIONS for {handler.name}:")
            for i, trade in enumerate(existing_trades, 1):
                print(f"  {i}. {trade.get('ticker', 'Unknown')} ...")
            # For Ryan, we'll proceed but with a warning
            log_func(f"Proceeding with new Ryan position (non-sequential pattern detected)")
```

This entire Ryan-specific block (the `if handler.name == "Ryan":` conditional and everything inside it) should be removed. The surrounding buy order execution logic should remain intact.

### Channel Parser Files to Delete

The following parser files should be completely deleted:
- `/Users/mautasimhussain/trading-bots/RHTBv5/channels/ryan.py` (277 lines) - Contains `RyanParser` with fast regex TRIM/EXIT parsing
- `/Users/mautasimhussain/trading-bots/RHTBv5/channels/eva.py` (127 lines) - Contains `EvaParser` with UPDATE filtering
- `/Users/mautasimhussain/trading-bots/RHTBv5/channels/will.py` (137 lines) - Contains `WillParser`
- `/Users/mautasimhussain/trading-bots/RHTBv5/channels/fifi.py` (258 lines) - Contains `FiFiParser` with SOLD TO OPEN detection

### Files to KEEP Unchanged

- `/Users/mautasimhussain/trading-bots/RHTBv5/channels/sean.py` - The parser we're keeping. It extends `BaseParser` and provides Sean-specific parsing prompts.
- `/Users/mautasimhussain/trading-bots/RHTBv5/channels/base_parser.py` - Base class for all parsers. Contains common OpenAI API calling, JSON parsing, action standardization (`_standardize_action`), and date parsing (`_smart_year_detection`, `_parse_monthly_expiration`). Sean's parser depends on this.
- `/Users/mautasimhussain/trading-bots/RHTBv5/channels/price_parser.py` - Used for the `!getprice` command, independent of channel trading.

### SeanParser Details (channels/sean.py)

The SeanParser is a straightforward implementation:

```python
class SeanParser(BaseParser):
    def __init__(self, openai_client, channel_id, config):
        super().__init__(openai_client, channel_id, config)

    def build_prompt(self) -> str:
        # Builds Sean-specific prompt for OpenAI
        # Handles both standard messages and replies
        # Returns JSON with action, ticker, strike, type, price, expiration, size
```

Sean's parser uses the default `parse_message()` from `BaseParser` (unlike Ryan's which overrides it with fast regex). This means all parsing goes through OpenAI for Sean's channel.

### Other Files with Channel References

The following files contain channel name references but should NOT require modification (the references are dynamic and will automatically work with fewer channels):

1. **`performance_tracker.py`** - Uses channel name as a parameter, not hardcoded. Queries like `get_open_trades_for_channel(channel_name)` will work with any channel name.

2. **`robinhood_positions.py`** - Uses channel name as a logging parameter only.

3. **`unified_csv_tracker.py`** - Has a test example using "Ryan" but this is only in the `if __name__ == "__main__"` block for testing.

4. **`latency_tracker.py`** - Has "Ryan" in a test example only.

5. **`main.py` `_handle_clear_command`** (lines 1158-1250) - Contains a channel mapping dictionary:
```python
channel_mapping = {
    'ryan': 'Ryan',
    'eva': 'Eva',
    'will': 'Will',
    'fifi': 'Fifi',
    'sean': 'Sean'
}
```
This should be simplified to only include Sean, but it's not strictly required since the command will just return "Unknown channel" for removed channels.

### Summary of Required Changes

1. **config.py**: Remove Ryan, Eva, Will, FiFi from `CHANNELS_CONFIG`. Keep only Sean entry with all its current settings.

2. **main.py** (lines 22-27): Remove imports for WillParser, EvaParser, RyanParser, FiFiParser. Keep only:
   ```python
   from channels.sean import SeanParser
   from channels.price_parser import PriceParser
   ```

3. **main.py** `_handle_clear_command` (optional cleanup): Simplify channel_mapping to only include Sean.

4. **trade_executor.py** (lines 416-428): Remove the Ryan-specific non-sequential trade detection block:
   ```python
   # DELETE THIS ENTIRE BLOCK:
   if handler.name == "Ryan":
       existing_trades = self.performance_tracker.get_open_trades_for_channel(handler.name)
       if existing_trades and len(existing_trades) > 0:
           # ... all the warning and logging code
   ```

5. **Delete files**:
   - `channels/ryan.py`
   - `channels/eva.py`
   - `channels/will.py`
   - `channels/fifi.py`

### Testing Approach

After making changes:
1. Start the bot with `python main.py`
2. Verify no import errors occur
3. Check logs for "Handlers updated" message showing only Sean's channel ID
4. Optionally run in TESTING_MODE with Sean's test channel to verify alert processing
5. Use `!status` command to verify only 1 active channel

### Technical Reference Details

**File Paths:**
- Main entry point: `/Users/mautasimhussain/trading-bots/RHTBv5/main.py`
- Config: `/Users/mautasimhussain/trading-bots/RHTBv5/config.py`
- Trade executor: `/Users/mautasimhussain/trading-bots/RHTBv5/trade_executor.py`
- Sean parser: `/Users/mautasimhussain/trading-bots/RHTBv5/channels/sean.py`
- Base parser: `/Users/mautasimhussain/trading-bots/RHTBv5/channels/base_parser.py`
- Files to delete: `/Users/mautasimhussain/trading-bots/RHTBv5/channels/ryan.py`, `eva.py`, `will.py`, `fifi.py`

**Sean Channel Configuration (to preserve):**
```python
"Sean": {
    "live_id": 1072555808832888945,
    "test_id": 1398211580470235176,
    "parser": "SeanParser",
    "multiplier": 1.0,
    "min_trade_contracts": 1,
    "initial_stop_loss": 0.50,
    "trailing_stop_loss_pct": 0.20,
    "buy_padding": 0.025,
    "sell_padding": 0.01,
    "model": "gpt-4o-2024-08-06",
    "color": 3066993,
    "description": "Sean's technical analysis based trades",
    "risk_level": "medium-high",
    "typical_hold_time": "1-4 hours",
    "trade_first_mode": True
}
```

## User Notes
- Reverting to this older bot version that worked well
- Goal is to have a clean, minimal codebase for Sean channel trading only
- Bot takes Discord alerts and trades options via Robinhood using robin_stocks API

## Work Log
<!-- Updated as work progresses -->
- [2026-01-27] Task created based on codebase analysis
