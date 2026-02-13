---
name: m-implement-eva-parser
branch: feature/implement-eva-parser
status: completed
created: 2026-02-12
completed: 2026-02-13
---

# Implement Eva Channel Parser

## Problem/Goal
Onboard Eva channel as a new trading signal source. Eva uses embedded messages with clear action markers:
- **Open** - New position entries
- **Close** - Could be trims OR full exits (parser must analyze context)
- **Update** - Ignored as commentary

## Channel Configuration
- **Live Channel ID:** 1072556084662902846
- **Sim Channel ID:** 1471756473242488885

## Success Criteria
- [x] Scrape last 500 messages from Eva channel for analysis
- [x] Analyze embed structure and patterns
- [x] Create EvaParser class extending BaseParser
- [x] Handle Open embeds (buy alerts)
- [x] Handle Close embeds (distinguish trim vs exit)
- [x] Ignore Update embeds (return null)
- [x] Add Eva to CHANNELS_CONFIG
- [x] Test parser against scraped messages
- [x] Enable in simulation mode for validation (enabled LIVE with all channels)

## Context Manifest

### How The Parser System Currently Works: Embed-Based Parsing Architecture

When a Discord message arrives in a monitored channel, the flow begins in `main.py` at the `on_message` event handler (line 913). The handler first checks if the channel has a registered parser by calling `self.channel_manager.get_handler(message.channel.id)`. If a handler exists, it extracts the message content via `_extract_message_content()` (lines 999-1063).

**Embed Extraction Flow:**

The `_extract_message_content()` method is critical for Eva's embed-based messages. Here's exactly how it works:

```python
def _extract_message_content(self, message, handler):
    # For messages with embeds:
    if message.embeds:
        embed = message.embeds[0]
        current_embed_title = embed.title or ""
        current_embed_desc = embed.description or ""

    # ...after handling forwards/replies...

    # KEY: For embed messages, returns a tuple (title, description)
    message_meta = (current_embed_title, current_embed_desc) if current_embed_title else current_content
```

For embed messages, `message_meta` is returned as a tuple `(title, description)` where:
- `title` contains the embed title (e.g., "Open", "Close", "Update")
- `description` contains the embed body with trade details

This tuple format is critical because RyanParser relies on it - the parser receives `message_meta` as the first argument to `parse_message()`, and dispatch logic checks `isinstance(message_meta, tuple)` to confirm it's an embed.

**RyanParser as the Embed Archetype:**

RyanParser (`channels/ryan.py`) is the primary reference for implementing EvaParser because it handles embed-based alerts using regex dispatch rather than LLM calls. Key architecture decisions:

1. **Bypasses LLM entirely** - Overrides `parse_message()` directly instead of `build_prompt()`:
   ```python
   def parse_message(self, message_meta, received_ts, logger, message_history=None):
       # Reject non-embed messages
       if not isinstance(message_meta, tuple) or len(message_meta) < 2:
           logger(f"[Ryan] Non-embed message, skipping")
           return [], 0

       title, description = message_meta[0], message_meta[1]
       # ... dispatch based on title
   ```

2. **Title-based dispatch** - The `_dispatch()` method routes based on embed title:
   ```python
   def _dispatch(self, title_upper, desc, color, logger):
       if title_upper == "ENTRY":
           return self._parse_entry(desc, logger)
       elif title_upper == "TRIM":
           return self._parse_trim(desc, logger)
       elif title_upper == "EXIT":
           return self._parse_exit(desc, logger)
       elif title_upper == "COMMENT":
           return []  # Non-actionable
   ```

3. **Regex parsing for entries** - Entry embeds are parsed with compiled regex:
   ```python
   _ENTRY_SPX = re.compile(r"\$SPX\s+(\d+)(p|c)\s*@\s*\$?([\d.]+)", re.IGNORECASE)

   def _parse_entry(self, desc, logger):
       match = self._ENTRY_SPX.search(desc)
       if not match:
           return []

       strike = int(match.group(1))
       opt_type = match.group(2).lower()
       price = float(match.group(3))
       today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

       return [{
           "action": "buy",
           "ticker": "SPX",
           "strike": strike,
           "type": "call" if opt_type == "c" else "put",
           "expiration": today,
           "price": price,
           "size": "full",
       }]
   ```

4. **Trim/Exit return market price** - For trims and exits, the title alone triggers the action:
   ```python
   def _parse_trim(self, desc, logger):
       return [{"action": "trim", "ticker": "SPX", "price": "market"}]

   def _parse_exit(self, desc, logger):
       return [{"action": "exit", "ticker": "SPX", "price": "market"}]
   ```

5. **Color fallback** - If title is unrecognized, falls back to embed color matching:
   ```python
   COLOR_ENTRY = 3066993      # green
   COLOR_TRIM = 16705372      # yellow
   COLOR_EXIT = 15158332      # red
   ```

**Eva's Key Difference: Close = Trim OR Exit**

Eva uses "Close" for both partial and full exits. This requires context analysis that RyanParser doesn't need. Two approaches:

**Option A: Position Ledger Query (Recommended)**
Query the position ledger to determine remaining quantity. If current Close quantity equals total position, it's an exit; otherwise, it's a trim:
```python
def _parse_close(self, desc, logger):
    # Parse ticker and quantity from embed description
    # Query position ledger: self.position_ledger.get_open_positions(ticker)
    # If closing full position: return action="exit"
    # If partial: return action="trim"
```

**Option B: LLM Hybrid**
Use regex for Open (fast), but fall back to LLM for Close when context is ambiguous. This is slower but more flexible.

### Position Ledger Integration for Close Resolution

The position ledger (`position_ledger.py`) provides the context needed to distinguish trim vs exit. Key methods:

```python
def get_open_positions(self, ticker: str = None) -> List[Position]:
    """Get all open positions, optionally filtered by ticker."""
    # Returns Position objects with:
    #   - ccid: Canonical Contract ID (SPY_20260128_595_C)
    #   - ticker, strike, option_type, expiration
    #   - total_quantity: Current contracts held
    #   - avg_cost_basis: Average entry price
    #   - status: 'open', 'trimmed', 'pending_exit', 'closed'

def resolve_position(self, ticker, hints=None, heuristic="fifo"):
    """Resolve ticker to specific position using weighted matching."""
    # Used when Close doesn't specify which position to act on
```

FiFiParser demonstrates position ledger injection for prompts (lines 30-48):
```python
def _get_open_positions_json(self) -> str:
    if not self.position_ledger:
        return "[]"
    positions = self.position_ledger.get_open_positions()
    pos_list = []
    for p in positions:
        pos_list.append({
            "ticker": p.ticker,
            "strike": p.strike,
            "type": p.option_type,
            "exp": p.expiration,
            "avg_cost": p.avg_cost_basis,
            "qty": p.total_quantity
        })
    return json.dumps(pos_list)
```

The ledger is automatically injected via `ChannelHandlerManager.update_handlers()` (line 92-96 in main.py):
```python
parser_instance = parser_class(
    self.openai_client, channel_id, {**config, "name": name},
    position_ledger=self.position_ledger
)
```

### CHANNELS_CONFIG Structure for Adding New Channels

New channels are registered in `config.py` CHANNELS_CONFIG (lines 117-193). Example structure:

```python
CHANNELS_CONFIG = {
    "Eva": {
        "live_id": 1072556084662902846,          # Eva's live channel ID
        "test_id": 1471756473242488885,          # Eva simulation channel
        "parser": "EvaParser",                    # Class name in channels/eva.py
        "multiplier": 0.5,                        # Portfolio fraction (0.5 = 5% of 10%)
        "min_trade_contracts": 0,                 # 0 = tracking only, >0 = live trading
        "initial_stop_loss": 0.30,                # 30% stop loss
        "trailing_stop_loss_pct": 0.20,           # 20% trailing stop
        "buy_padding": 0.025,                     # 2.5% price padding for buys
        "sell_padding": 0.01,                     # 1% price padding for sells
        "model": "gpt-4o-mini",                   # LLM model (ignored if regex-based)
        "color": 9936031,                         # Embed color for alerts (pick unique)
        "description": "Eva's structured option trades",
        "risk_level": "medium",
        "typical_hold_time": "1-4 hours",
        "trade_first_mode": True,                 # Execute before alerting
        "message_history_limit": 0,               # Embeds are self-contained (like Ryan)
        "resting_order_timeout": 300              # 5 minutes for resting buy orders
    },
    # ... other channels
}
```

Key fields explained:
- `min_trade_contracts`: Set to 0 for tracking-only mode during development/validation
- `message_history_limit`: Set to 0 for embed-based parsers (embeds are self-contained)
- `parser`: Must match the class name exactly; imported in main.py (line 28 area)

### Parser Import Registration in main.py

After creating `channels/eva.py`, add the import at the top of `main.py` (around line 27):
```python
from channels.ryan import RyanParser
from channels.eva import EvaParser  # ADD THIS
```

The `ChannelHandlerManager` dynamically instantiates parsers by looking up the class name in `globals()`:
```python
parser_class_name = config.get("parser")  # e.g., "EvaParser"
if parser_class_name in globals():
    parser_class = globals()[parser_class_name]  # Gets EvaParser class
```

### Message Scraping Pattern for Analysis

A scraping script exists at `tsc_analysis/ian_analysis.py` that can be adapted for Eva:

```python
class EvaAnalyzer:
    def __init__(self, output_dir="tsc_analysis"):
        self.client = discord.Client()

    async def scrape_and_analyze(self):
        channel = self.client.get_channel(EVA_CHANNEL_ID)

        messages = []
        async for message in channel.history(limit=500):
            msg_data = await self.parse_discord_message(message, channel)
            messages.append(msg_data)

        # Reverse to chronological order
        messages.reverse()
        self.export_raw_messages()  # CSV for manual review
```

Key fields to capture:
- `embed.title`: "Open", "Close", "Update"
- `embed.description`: Contract details
- `embed.color`: May help distinguish action types
- `embed.fields`: Some embeds use fields for structured data

### Trade Execution Integration

After parsing, results flow to `trade_executor.py`'s `process_trade()` method (line 779). The executor:

1. Calls `handler.parse_message(message_meta, received_ts, log_func, message_history)`
2. For each parsed result, normalizes keys and extracts action
3. Looks up channel config for risk parameters
4. For buys: Calculates position size, places order via `_execute_buy()`
5. For trims/exits: Resolves position via ledger, places sell order

The executor expects parsed results in this format:
```python
{
    "action": "buy" | "trim" | "exit" | "null",
    "ticker": "SPY",
    "strike": 600,
    "type": "call" | "put",
    "expiration": "2026-02-12",  # YYYY-MM-DD format
    "price": 2.50,               # or "market" or "BE"
    "size": "full" | "half" | "small"  # for buys only
}
```

### Technical Reference Details

#### Parser Class Template (EvaParser)

```python
# channels/eva.py
from .base_parser import BaseParser, get_parse_cache
from datetime import datetime, timezone
import re

class EvaParser(BaseParser):
    # Embed colors for fallback dispatch (get from Eva's actual embeds)
    COLOR_OPEN = None    # Green typically
    COLOR_CLOSE = None   # Red/yellow
    COLOR_UPDATE = None  # Blue typically

    # Regex patterns (analyze scraped embeds to determine format)
    _ENTRY_PATTERN = re.compile(
        r"(?:Pattern here after analyzing embeds)",
        re.IGNORECASE,
    )

    def __init__(self, openai_client, channel_id, config, **kwargs):
        super().__init__(openai_client, channel_id, config, **kwargs)

    def build_prompt(self) -> str:
        """Not used - EvaParser bypasses LLM. Required by ABC."""
        return ""

    def parse_message(self, message_meta, received_ts, logger, message_history=None):
        """Override to use regex dispatch instead of LLM."""
        start = time.monotonic()

        # Reject non-embed messages
        if not isinstance(message_meta, tuple) or len(message_meta) < 2:
            logger(f"[Eva] Non-embed message, skipping")
            return [], 0

        title, description = message_meta[0], message_meta[1]

        # Cache check
        cache = get_parse_cache()
        cached = cache.get(message_meta, message_history)
        if cached is not None:
            return cached

        # Dispatch based on title
        title_upper = (title or "").strip().upper()
        result = self._dispatch(title_upper, description, logger)

        # Add metadata
        now = datetime.now(timezone.utc).isoformat()
        for entry in result:
            entry["channel_id"] = self.channel_id
            entry["received_ts"] = now

        latency_ms = (time.monotonic() - start) * 1000
        out = (result, latency_ms)
        cache.set(message_meta, out, message_history)
        return out

    def _dispatch(self, title_upper, desc, logger):
        if title_upper == "OPEN":
            return self._parse_open(desc, logger)
        elif title_upper == "CLOSE":
            return self._parse_close(desc, logger)
        elif title_upper == "UPDATE":
            return []  # Commentary
        return []

    def _parse_open(self, desc, logger):
        # TODO: Implement after analyzing embed format
        pass

    def _parse_close(self, desc, logger):
        # TODO: Determine trim vs exit using position ledger
        pass
```

#### Configuration Entry

```python
# config.py - Add to CHANNELS_CONFIG
"Eva": {
    "live_id": 1072556084662902846,
    "test_id": 1471756473242488885,
    "parser": "EvaParser",
    "multiplier": 0.5,
    "min_trade_contracts": 0,  # Start with tracking only
    "initial_stop_loss": 0.30,
    "trailing_stop_loss_pct": 0.20,
    "buy_padding": 0.025,
    "sell_padding": 0.01,
    "model": "gpt-4o-mini",  # Not used for regex parser
    "color": 9936031,  # Pick unique color
    "description": "Eva's structured option trades",
    "risk_level": "medium",
    "typical_hold_time": "1-4 hours",
    "trade_first_mode": True,
    "message_history_limit": 0,  # Embeds are self-contained
    "resting_order_timeout": 300
},
```

#### File Locations

- **Parser implementation**: `/Users/mautasimhussain/trading-bots/RHTBv5/channels/eva.py` (create new)
- **Parser import**: `/Users/mautasimhussain/trading-bots/RHTBv5/main.py` (line ~28)
- **Channel config**: `/Users/mautasimhussain/trading-bots/RHTBv5/config.py` (CHANNELS_CONFIG)
- **Scraping script**: `/Users/mautasimhussain/trading-bots/RHTBv5/tsc_analysis/eva_analysis.py` (create new)
- **Scraped messages**: `/Users/mautasimhussain/trading-bots/RHTBv5/tsc_analysis/eva_raw_messages.csv` (output)
- **Base parser reference**: `/Users/mautasimhussain/trading-bots/RHTBv5/channels/base_parser.py`
- **Ryan parser reference**: `/Users/mautasimhussain/trading-bots/RHTBv5/channels/ryan.py`

#### Required Environment Variables

No new environment variables needed. Uses existing:
- `DISCORD_USER_TOKEN` - Discord user token for scraping
- `OPENAI_API_KEY` - Only needed if hybrid LLM approach is used

#### Cache Integration

RyanParser uses the global parse cache for deduplication:
```python
from .base_parser import get_parse_cache

cache = get_parse_cache()
cached = cache.get(message_meta, message_history)
if cached is not None:
    return cached

# ... parsing logic ...

cache.set(message_meta, result, message_history)
```

### Implementation Checklist

1. **Scrape Eva channel** - Create `tsc_analysis/eva_analysis.py` based on `ian_analysis.py`
2. **Analyze embed structure** - Document title patterns, description format, color codes
3. **Design regex patterns** - Based on actual embed content structure
4. **Create EvaParser class** - Extend BaseParser, override `parse_message()` and `build_prompt()`
5. **Implement title dispatch** - Open/Close/Update routing
6. **Implement Close resolution** - Query position ledger for trim vs exit determination
7. **Add to CHANNELS_CONFIG** - Start with `min_trade_contracts=0` for tracking
8. **Import in main.py** - Add `from channels.eva import EvaParser`
9. **Test against scraped messages** - Validate parsing accuracy
10. **Enable simulation mode** - Set `min_trade_contracts=1` with test_id channel

## User Notes
- Eva uses embedded messages (similar to Ryan channel pattern)
- Close alerts need context analysis to determine if trim or full exit
- Update alerts should be ignored as commentary
- Start with message scraping and analysis before implementation
- **Existing scrapers**: Use `tsc_analysis/ian_analysis.py` or `tsc_analysis/fifi_analysis.py` as base for Eva scraping

## Work Log

### 2026-02-12
- Task created with full context manifest

### 2026-02-13

#### Completed
- Implemented EvaParser (hybrid regex + LLM) in `channels/eva.py`
  - OPEN embeds: regex-based parsing (~0ms latency)
  - CLOSE embeds: LLM-based trim vs exit determination via position ledger
  - UPDATE embeds: ignored (non-actionable)
- Added Eva to CHANNELS_CONFIG with live/test channel IDs
- Enabled all 5 channels (Sean, FiFi, Ryan, Ian, Eva) for live trading with `min_trade_contracts=2`
- Updated cascade timing for 0DTE speed:
  - Buy cascade: 10s waits, bid_plus_tick for queue priority
  - Trim cascade: 10s waits, ask_minus_tick (stay on ask side)
  - Exit cascade: 5s waits, bid_plus_tick (faster fills)
- Implemented 20% stop loss (entry × 0.80) with 5-minute grace period
- Added break-even stop after tier1 trim (entry + 1 tick to cover fees)
- Implemented flash crash detection (>20% drop in <10s triggers emergency exit)
- Implemented CBOE tick snapping for SPX options ($0.05 under $3, $0.10 above)
- Fixed critical tick size bug: non-SPX symbols now correctly use $0.01

#### Key Files Modified
- `channels/eva.py` (new) - Hybrid parser implementation
- `config.py` - Channel configs, cascade steps, AUTO_EXIT_CONFIG
- `trade_executor.py` - bid_plus_tick/ask_minus_tick price types, tick size fix
- `auto_exit_manager.py` - Flash crash detection, break-even stop logic
- `main.py` - EvaParser import

#### Decisions
- Used hybrid regex + LLM approach: regex for Open (speed), LLM for Close (context needed)
- Enabled live trading for all 5 channels based on parsing validation results
- Kept 5-minute stop loss grace period (Ryan tests EMAs, expects initial drawdown)
- Set break-even = entry + 1 tick after trim (covers fees, ensures scratch is free)
