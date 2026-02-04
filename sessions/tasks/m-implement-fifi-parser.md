---
name: m-implement-fifi-parser
branch: feature/implement-fifi-parser
status: pending
created: 2026-02-03
---

# Implement FiFi Channel Parser

## Problem/Goal
Build a `FiFiParser` class to parse FiFi's (sauced2002) plain-English Discord trading alerts into structured trade signals. FiFi's messaging style is conversational and non-standardized, requiring enhanced LLM prompting and position-aware context injection.

Based on research from `m-research-fifi-channel-parsing`, which analyzed 1000 messages and identified all linguistic patterns, message distribution (29.9% actionable), and 5 approved core enhancements.

## Success Criteria
- [ ] Create `channels/fifi.py` with `FiFiParser` extending `BaseParser`
- [ ] Add FiFi to `CHANNELS_CONFIG` in `config.py` (tracking-only: min_trade_contracts=0)
- [ ] Add `FiFiParser` import to `main.py`
- [ ] Implement `build_prompt()` with all 5 approved enhancements:
  - [ ] Position ledger injection (open positions as compact JSON in prompt)
  - [ ] Reply context with clear PRIMARY/REPLYING TO tags
  - [ ] Last 10 messages with time deltas
  - [ ] Negative constraint firewall (Do NOT rules)
  - [ ] Role ping signal (has_alert_ping flag)
- [ ] Implement custom `_normalize_entry()` for FiFi-specific post-processing
- [ ] Include 8-10 few-shot examples from real FiFi messages
- [ ] Bot starts successfully with FiFi channel registered
- [ ] Test parse against 10+ real FiFi messages with correct classification

## Context Manifest
<!-- Added by context-gathering agent -->

### How the Channel Parser System Currently Works

When a Discord message arrives, `on_message()` in `main.py` (line 530) fires. The method checks if the channel ID has a registered handler by calling `self.channel_manager.get_handler(message.channel.id)` (line 543). If a handler is found, the bot extracts message content via `_extract_message_content()` (line 548), fetches message history (line 552, currently `limit=5`), and then calls `self.trade_executor.process_trade()` (line 562) with the handler, message metadata, raw message string, sim mode flag, received timestamp, message ID, is_edit flag, event loop, and message history.

The `_extract_message_content()` method (lines 628-692) handles three content types:
1. **Forwarded messages**: Checks `message.message_snapshots`, extracts forwarded content. Returns `(comment, forwarded_content)` tuple if the user commented, or just the forwarded string.
2. **Reply messages**: When `message.reference.resolved` is a Discord Message, it extracts both the current message content and the original replied-to message content. Returns a tuple `(current_full_text, original_full_text)`.
3. **Standard messages**: Returns the message content as a string (or a tuple of embed title/description if the message has embeds).

The `get_channel_message_history()` method (lines 694-737) fetches recent messages from the channel via `channel.history(limit=limit+1)`. It excludes the current message by ID, extracts content from embeds or plain text, truncates to 200 characters, prepends a `[HH:MM:SS]` timestamp, and returns the list reversed into chronological order (oldest first). Currently called with `limit=5` for Sean's channel.

**Parser Registration Flow**: `ChannelHandlerManager.update_handlers()` (lines 76-94) iterates over `CHANNELS_CONFIG`, looks up each parser class by name using `globals()[parser_class_name]`, instantiates with `parser_class(self.openai_client, channel_id, {**config, "name": name})`, and maps `channel_id -> parser_instance`. This means the parser class must be imported at the top of main.py AND appear in globals. Currently only `SeanParser` and `PriceParser` are imported (lines 24-25).

### How BaseParser Works (What FiFiParser Inherits)

`BaseParser` at `/Users/mautasimhussain/trading-bots/RHTBv5/channels/base_parser.py` is a 761-line abstract base class. Its constructor signature is:

```python
def __init__(self, openai_client: OpenAI, channel_id: int, config: dict):
```

It stores `self.client` (OpenAI), `self.channel_id`, `self.name` (from `config["name"]`), `self.model` (from `config.get("model")`), `self.color` (from `config.get("color")`), `self._current_message_meta` (set to None initially), and `self._message_history` (empty list). The config dict it receives is `{**CHANNELS_CONFIG[name], "name": name}`.

**The `parse_message()` Method** (lines 424-519) is the main entry point called by TradeExecutor. Its signature:

```python
def parse_message(self, message_meta, received_ts: datetime, logger, message_history: Optional[List[str]] = None) -> Tuple[List[Dict], float]:
```

The flow inside `parse_message()`:
1. Check the global `ParseCache` for a cached response matching this message+history.
2. Set `self._current_message_meta = message_meta` and `self._message_history = message_history or []`.
3. Call `self.build_prompt()` -- the abstract method that subclasses override.
4. Call `self._call_openai(prompt, logger)` which tries gpt-4o-mini first, then the configured fallback model.
5. Ensure response is a list of dicts.
6. For each dict: standardize the action using `_standardize_action()`, skip null actions, add `channel_id` and `received_ts` metadata, call `self._normalize_entry(entry)` for subclass-specific post-processing, re-standardize action after subclass normalization, validate against Pydantic schema (non-blocking), append to results.
7. Cache and return `(normalized_results, latency_ms)`.

**The `_normalize_entry()` Method** (lines 692-722) is the hook for subclass customization. The base implementation ONLY handles date format fallback: if the `expiration` field is not already in `YYYY-MM-DD` format, it tries `_parse_monthly_expiration()` then `_smart_year_detection()`. Subclasses override this to add their own normalization, calling `super()._normalize_entry(entry)` first.

**The `_standardize_action()` Method** (lines 241-282) maps many action word variations to four canonical values: "buy", "trim", "exit", "null". This is called BEFORE `_normalize_entry()` and AFTER it (double-check). Key mappings include "sold" -> "exit", "out" -> "exit", "half" -> "trim", "some" -> "trim".

**Pydantic Alert Schemas** (lines 100-195):
- `BuyAlert`: action="buy", ticker (str), strike (float), type ("call"/"put"), expiration (str YYYY-MM-DD), price (float), size ("full"/"half"/"lotto") default "full"
- `TrimAlert`: action="trim", ticker (str), strike (optional float), type (optional), expiration (optional), price (float or "BE")
- `ExitAlert`: action="exit", ticker (str), strike (optional float), type (optional), expiration (optional), price (float or "BE")
- `CommentaryAlert`: action="null", message (optional str)

The `ExitAlert` schema requires `price` as either a float or the literal string "BE". However, FiFi uses "market" for exits without price (e.g., "got stopped on rest of RGTI"). The `_standardize_action()` method handles "stopped" -> "exit", and the trade executor handles "market" price by looking up market data. The Pydantic validation is non-blocking (line 498-504), so a price of "market" will fail validation but the raw parsed data will still be used.

### How SeanParser Works (The Reference Implementation)

`SeanParser` at `/Users/mautasimhussain/trading-bots/RHTBv5/channels/sean.py` is 184 lines. It is the ONLY currently active channel parser and serves as the canonical example for building FiFiParser.

**Structure**: Extends `BaseParser`. Constructor calls `super().__init__(openai_client, channel_id, config)` with no additional initialization. Overrides ONLY `build_prompt()`. Does NOT override `_normalize_entry()` (uses base class default).

**Prompt Design Patterns Used by Sean**:
1. Dynamic date injection: `today_str` and `current_year` computed at prompt build time.
2. Reply handling: Checks `isinstance(self._current_message_meta, tuple)` to distinguish replies from standard messages. Replies get `primary_message` and `context_message`.
3. Prompt structure: System role description, MESSAGE CONTEXT rules, ACTION DEFINITIONS, DATE RULES (with YYYY-MM-DD conversion), OUTPUT FORMAT RULES, SIZE RULES, WEEKLY TRADE PLAN FILTERING, EXTRACTION LOGIC, ACTION VALUES enforcement, few-shot examples, MESSAGE TO PARSE section.
4. Message history injection: Appended at the end of the prompt, outside the main instruction block. Uses `self._message_history` with chronological ordering.
5. Key patterns: `PRIMARY MESSAGE: "{primary_message}"` with ORIGINAL MESSAGE appended if reply.

**Important**: Sean's parser asks the LLM to convert dates to YYYY-MM-DD directly. The old FiFi parser did NOT do this -- it asked the LLM to return raw date text and relied on `_normalize_entry()` fallback. The research task recommends FiFi's new parser SHOULD convert dates in the prompt like Sean does, since it reduces post-processing complexity.

### The Old FiFi Parser (Recovered from Git)

The previous `FiFiParser` was 258 lines and was deleted in commit `dc58787`. It provides important patterns:

**Key Differences from Sean**:
1. **STO (Sold to Open) Pattern**: Extensive prompt instructions and `_normalize_entry()` fallback to detect "SOLD TO OPEN" language and map to "exit". The research found ZERO STO occurrences in the last 1000 messages, so this should be minimal.
2. **Direct Buy Recognition**: No action word needed -- just ticker+strike+type+expiry+price implicitly means "buy".
3. **Stop-out Detection**: Phrases like "stopped out", "got stopped", "we got stopped" always map to "exit" via `_normalize_entry()`.
4. **Embedded Contract Notation**: Regex `^([A-Z]+)(\d+(?:\.\d+)?)(c|p|call|put)$` to parse "BMNR50p" into ticker/strike/type.
5. **Date Handling**: Did NOT convert dates in the prompt -- returned raw date text and used base class fallback.
6. **Default 0DTE**: If no expiration for a buy, default to today's date.
7. **Size Normalization**: "some"/"small"/"starter" -> "half", "tiny"/"lotto" -> "lotto".

**The old `_normalize_entry()` method** called `super()._normalize_entry(entry)` first (for date fallback), then applied: STO detection with premium extraction, stop-out phrase detection, size normalization, 0DTE default, embedded contract notation regex. This pattern should be followed in the new implementation.

### CRITICAL: Position Ledger Injection Enhancement (Architecture Gap)

The research task's highest-impact approved enhancement is injecting open positions into the FiFi prompt. However, there is a significant architecture gap:

**Currently, parsers do NOT have access to the position ledger.** The `ChannelHandlerManager.update_handlers()` method (line 88) creates parser instances with only three arguments: `openai_client`, `channel_id`, and `config`. The `PositionLedger` instance lives on the `EnhancedDiscordClient` (line 121: `self.position_ledger = PositionLedger(POSITION_LEDGER_DB)`) and is passed to `TradeExecutor` (line 143), but never to parsers.

**Implementation approach**: The FiFiParser constructor needs to accept an optional `position_ledger` parameter. This means either:
- **Option A**: Modify `ChannelHandlerManager.update_handlers()` to pass `position_ledger` to parser constructors. This requires changing the method to accept the ledger as a parameter, and updating the parser instantiation call. This would be the cleanest approach but touches shared infrastructure.
- **Option B**: Add a setter method `set_position_ledger(ledger)` on BaseParser/FiFiParser that `ChannelHandlerManager` or `EnhancedDiscordClient` calls after construction. This is less clean but avoids modifying BaseParser's constructor signature.
- **Option C**: Pass the ledger via the config dict as `config["position_ledger"]`. This is hacky but requires zero changes to shared infrastructure -- just add it to the CHANNELS_CONFIG or merge it in at handler update time.

**Recommended**: Option A. Modify `BaseParser.__init__` to accept an optional `position_ledger=None` parameter (backward compatible), and modify `ChannelHandlerManager.update_handlers()` to pass it. The SeanParser does not use it, so no changes needed there. The `ChannelHandlerManager` already has access to the ledger's parent (`EnhancedDiscordClient`) but currently only stores `self.openai_client`. It needs to also store `self.position_ledger`.

Specifically, `ChannelHandlerManager.__init__` (line 72-74) needs to accept `position_ledger`, and `update_handlers()` (line 88) needs to pass it:
```python
# Current (line 88):
parser_instance = parser_class(
    self.openai_client, channel_id, {**config, "name": name}
)

# Needs to become:
parser_instance = parser_class(
    self.openai_client, channel_id, {**config, "name": name}, position_ledger=self.position_ledger
)
```

And `BaseParser.__init__` (line 223) needs:
```python
# Current:
def __init__(self, openai_client: OpenAI, channel_id: int, config: dict):

# Needs to become:
def __init__(self, openai_client: OpenAI, channel_id: int, config: dict, position_ledger=None):
    ...
    self.position_ledger = position_ledger
```

The `EnhancedDiscordClient.__init__` (line 132) creates `ChannelHandlerManager(self.openai_client)` -- this call also needs to pass the ledger.

**Position Ledger Query for Prompt Injection**: The `PositionLedger.get_open_positions(ticker=None)` method (line 465) returns all open positions when called with no ticker filter. The Position dataclass has a `channel` field (line 72) that stores which channel opened the position (e.g., "FiFi", "Sean", "manual"). To filter FiFi-channel positions, query all open positions and filter in Python:

```python
positions = self.position_ledger.get_open_positions()
fifi_positions = [p for p in positions if p.channel == "FiFi"]
```

The compact JSON format for prompt injection should include: ticker, strike, option_type, expiration, avg_cost_basis. The Position dataclass (line 52-77) provides all these fields.

### Trade Execution Flow After Parsing

After `parse_message()` returns, the `TradeExecutor._blocking_handle_trade()` method (line 404) processes each parsed result:

1. Calls `handler.parse_message()` with message_meta, received_ts, log_func, message_history.
2. For each result, calls `_normalize_keys()` to standardize key names.
3. For trim/exit actions, attempts position resolution through a 5-layer cascade:
   - Position ledger (`resolve_position()` with weighted hints)
   - Position manager (`find_position()`)
   - Performance tracker (`find_open_trade_by_ticker()`)
   - Feedback CSV (`get_recent_parse_for_channel()`)
   - Robinhood API (`get_contract_info_for_ticker()`)
4. Checks `min_trade_contracts` in channel config -- if 0, sets `is_tracking_only = True` and returns without executing.
5. For real trades, executes via `_execute_buy_order()` or `_execute_sell_order()` with cascade pricing.
6. Records results in performance tracker and position manager.
7. Sends alerts via webhook.

The `min_trade_contracts=0` tracking-only flow (lines 890-915) is critical for FiFi's initial deployment. When this is 0:
- `trade_obj['quantity'] = 0`
- `trade_obj['is_tracking_only'] = True`
- Market data is still fetched for tracking
- No actual Robinhood order is placed
- The trade is recorded in performance tracker as `status='tracking_only'`
- Position manager is NOT updated (line 623: `if not trade_obj.get('is_tracking_only')`)

### FiFi-Specific Prompt Requirements from Research

The research analyzed 1000 messages (2025-12-16 to 2026-02-04) and identified 298 actionable messages (29.9%). The five approved core enhancements for the FiFi prompt are:

**Enhancement 1: Position Ledger Injection** -- Inject `OPEN POSITIONS: [{ticker, strike, type, exp, avg_cost}]` as compact JSON into the system prompt. This allows the LLM to resolve ambiguous trims/exits like "trim $7" to the correct position. See architecture gap discussion above for how to wire this up.

**Enhancement 2: Reply Context with Clear Tags** -- Use `PRIMARY: [message]` / `REPLYING TO: [original]` labels. 50 of 298 actionable messages (16.8%) are reply-based where the trim/exit has minimal info and relies on the replied-to message for contract details. The bot's `on_message()` already extracts reply context into the `message_meta` tuple -- `build_prompt()` just needs to format it properly.

**Enhancement 3: Last 10 Messages with Time Deltas** -- Expand from Sean's 5 messages to 10 for FiFi's conversational style. Prepend time delta tags like `[2m ago]`, `[15m ago]` instead of absolute timestamps. This requires either changing the `get_channel_message_history()` call from `limit=5` to `limit=10` for FiFi specifically, or having FiFi's `build_prompt()` handle the time delta formatting. The simplest approach: pass more history from `on_message()`. Since the limit is passed at the call site (main.py line 552-553), we could either:
- Make the limit handler-specific (check `handler.name` before calling)
- Pass the limit as a config value in CHANNELS_CONFIG
- Or simply increase the global limit to 10 (Sean doesn't care about extras)

**Enhancement 4: Negative Constraint Firewall** -- Explicit "Do NOT" rules in the prompt to prevent false positives. This is pure prompt engineering -- no code changes needed beyond what goes in `build_prompt()`.

**Enhancement 5: Role Ping Signal** -- FiFi appends `<@&1369304547356311564>` to actionable messages. Pass `has_alert_ping: true/false` to the prompt. This requires detecting the role mention in the message content. The message content string will contain the raw role mention -- check `"<@&1369304547356311564>" in primary_message`.

### Few-Shot Examples for the Prompt

The research provides extensive real-world examples that should be used as few-shot examples in the prompt. At minimum, include examples from these categories:

**BUY Examples**:
- `"in PLTR 2/6 $155p $2.70"` -> buy PLTR 2026-02-06 155 put @ 2.70, size full
- `"in MO 0dte $61c .08 LOTTO SIZE"` -> buy MO today 61 call @ 0.08, size lotto
- `"TSLA 480p 0dte 1.40"` -> buy TSLA today 480 put @ 1.40 (implicit buy)
- `"added full size into MRK 2/20 $110c here at $2.90"` -> buy MRK 2/20 110 call @ 2.90

**TRIM Examples**:
- `"trim .18"` (reply to MO buy) -> trim MO @ 0.18
- `"Trimmed spy 7.20 from 4.60 for 2/20"` -> trim SPY @ 7.20
- `"sold 1/2 SLV here .20 +100%"` -> trim SLV @ 0.20

**EXIT Examples**:
- `"out TSLA 1.4"` -> exit TSLA @ 1.40
- `"Out PLTR BE here"` -> exit PLTR @ BE
- `"all out SNDK for now"` -> exit SNDK @ market
- `"got stopped on rest of RGTI"` -> exit RGTI @ market

**NULL Examples**:
- Trim summary with haircut emoji -> null
- `"Eyeing SMH short on the next bounce"` -> null
- Open positions list -> null
- `"SL is HOD"` -> null

### Custom `_normalize_entry()` Post-Processing

The FiFi parser needs a custom `_normalize_entry()` method that performs these operations after calling `super()._normalize_entry(entry)`:

1. **Embedded contract notation regex**: `^([A-Z]+)(\d+(?:\.\d+)?)(c|p)$` to parse "BMNR50p" -> ticker="BMNR", strike=50, type="put".
2. **"from $X" stripping**: Messages like "trim QQQ puts at 3.20 from .43" -- extract 3.20 as the current price, ignore "from .43" (that is entry price context). The LLM should handle this, but `_normalize_entry()` can be a safety net.
3. **Size normalization**: Map non-standard sizes: "1/4"/"couple cons"->"half", "1/8"/"super small"->"lotto", "starter"->"half", "some"/"small"->"half".
4. **Default 0DTE**: If `action=="buy"` and no expiration, default to today's date.
5. **"rest"/"runners"/"last piece" in exits**: These confirm full exit (already handled by action="exit").
6. **Stop-out phrase detection**: Fallback check for "stopped out", "got stopped", "stop hit" in the original message to force action="exit".
7. **Ticker cleanup**: Remove `$` prefix (already handled by Pydantic validators), handle uppercase normalization.

### Technical Reference Details

#### Files to Create

- `/Users/mautasimhussain/trading-bots/RHTBv5/channels/fifi.py` -- New FiFiParser class

#### Files to Modify

- `/Users/mautasimhussain/trading-bots/RHTBv5/config.py` -- Add FiFi entry to CHANNELS_CONFIG (after line 123)
- `/Users/mautasimhussain/trading-bots/RHTBv5/main.py` -- Add `from channels.fifi import FiFiParser` import (after line 24), optionally increase message history limit for FiFi, pass position_ledger to ChannelHandlerManager
- `/Users/mautasimhussain/trading-bots/RHTBv5/channels/base_parser.py` -- Add optional `position_ledger` parameter to `__init__` (line 223)

#### CHANNELS_CONFIG Entry for FiFi

Based on the old config and research recommendations:
```python
"FiFi": {
    "live_id": 1368713891072315483,
    "test_id": 1402850612995031090,
    "parser": "FiFiParser",
    "multiplier": 1.0,
    "min_trade_contracts": 0,      # Tracking-only mode initially
    "initial_stop_loss": 0.50,
    "trailing_stop_loss_pct": 0.20,
    "buy_padding": 0.025,
    "sell_padding": 0.01,
    "model": "gpt-4o-2024-08-06",
    "color": 15277667,             # Pink (0xE91E63)
    "description": "FiFi's swing and momentum trades",
    "risk_level": "medium",
    "typical_hold_time": "30 minutes - 4 hours",
    "trade_first_mode": True
}
```

#### BaseParser Constructor Signature Change

```python
# /Users/mautasimhussain/trading-bots/RHTBv5/channels/base_parser.py line 223
# Current:
def __init__(self, openai_client: OpenAI, channel_id: int, config: dict):
    self.client = openai_client
    self.channel_id = channel_id
    self.name = config["name"]
    self.model = config.get("model", "gpt-4o-2024-08-06")
    self.color = config.get("color", 7506394)
    self._current_message_meta = None
    self._message_history = []

# Needs to become:
def __init__(self, openai_client: OpenAI, channel_id: int, config: dict, position_ledger=None):
    self.client = openai_client
    self.channel_id = channel_id
    self.name = config["name"]
    self.model = config.get("model", "gpt-4o-2024-08-06")
    self.color = config.get("color", 7506394)
    self._current_message_meta = None
    self._message_history = []
    self.position_ledger = position_ledger
```

#### ChannelHandlerManager Changes

```python
# /Users/mautasimhussain/trading-bots/RHTBv5/main.py lines 72-94
# Current:
class ChannelHandlerManager:
    def __init__(self, openai_client):
        self.openai_client = openai_client
        self.handlers = {}

# Needs to become:
class ChannelHandlerManager:
    def __init__(self, openai_client, position_ledger=None):
        self.openai_client = openai_client
        self.position_ledger = position_ledger
        self.handlers = {}

# And update_handlers line 88:
parser_instance = parser_class(
    self.openai_client, channel_id, {**config, "name": name},
    position_ledger=self.position_ledger
)

# And the construction call on line 132:
self.channel_manager = ChannelHandlerManager(self.openai_client, self.position_ledger)
```

Note: Since `self.position_ledger` is initialized on line 121 and `ChannelHandlerManager` is created on line 132, the ledger will already exist by the time the channel manager is created. The ordering in `__init__` is safe.

#### SeanParser Compatibility

SeanParser's constructor (line 6-7) calls `super().__init__(openai_client, channel_id, config)`. After the BaseParser change, this still works because `position_ledger` defaults to `None`. The SeanParser will simply have `self.position_ledger = None` which it never accesses.

#### FiFiParser Class Structure

```python
# channels/fifi.py
from .base_parser import BaseParser
from datetime import datetime, timezone
import re

class FiFiParser(BaseParser):
    FIFI_ALERT_ROLE_ID = "1369304547356311564"

    def __init__(self, openai_client, channel_id, config, position_ledger=None):
        super().__init__(openai_client, channel_id, config, position_ledger=position_ledger)

    def _get_open_positions_json(self) -> str:
        """Query position ledger for open positions, return compact JSON for prompt."""
        if not self.position_ledger:
            return "[]"
        positions = self.position_ledger.get_open_positions()
        # Filter and format as compact JSON
        pos_list = []
        for p in positions:
            pos_list.append({
                "ticker": p.ticker,
                "strike": p.strike,
                "type": p.option_type,
                "exp": p.expiration,
                "avg_cost": p.avg_cost_basis
            })
        import json
        return json.dumps(pos_list)

    def build_prompt(self) -> str:
        # Dynamic date, reply handling, prompt construction
        # ... (see detailed prompt design in research findings)
        pass

    def _normalize_entry(self, entry: dict) -> dict:
        entry = super()._normalize_entry(entry)
        # FiFi-specific post-processing
        # ... (size normalization, 0DTE default, embedded ticker regex, stop-out detection)
        return entry
```

#### Position Dataclass Fields (for Ledger Injection)

The `Position` dataclass at `/Users/mautasimhussain/trading-bots/RHTBv5/position_ledger.py` line 52-77:
```python
@dataclass
class Position:
    ccid: str                        # e.g., "SPY_20260128_595_C"
    ticker: str                      # e.g., "SPY"
    strike: float                    # e.g., 595.0
    option_type: str                 # "call" or "put"
    expiration: str                  # "2026-01-28" (YYYY-MM-DD)
    total_quantity: int              # Number of contracts
    avg_cost_basis: float            # Average entry price
    status: str                      # "open", "trimmed", "pending_exit", etc.
    channel: Optional[str]           # "FiFi", "Sean", "manual"
    first_entry_time: str            # ISO format datetime
    last_update_time: str            # ISO format datetime
    pending_exit_since: Optional[str]
    notes: Optional[str]
    order_id: Optional[str]
```

#### Message History Time Delta Formatting

For Enhancement 3, the message history currently comes formatted as `[HH:MM:SS] content` (main.py line 727). For FiFi, we want `[Xm ago] content` instead. Two approaches:
- **Approach A**: Modify `get_channel_message_history()` to accept a `format_type` parameter ("timestamp" vs "delta"). This is cleaner but touches shared code.
- **Approach B**: Have FiFi's `build_prompt()` reformat the history strings, parsing out the `[HH:MM:SS]` timestamps and converting to deltas. This avoids touching main.py but is more fragile.
- **Approach C**: Pass the raw Discord message objects to the parser and let it handle formatting. This is the most flexible but requires significant refactoring.

**Recommended**: Approach A or B. If using Approach B, the history strings will look like `[14:32:05] in PLTR 2/6 $155p $2.70`. The parser can parse the timestamp, compute the delta from now, and reformat. However, this assumes UTC timestamps (which is what `msg.created_at.strftime("%H:%M:%S")` produces). Alternatively, a simpler version of Approach A: just add an optional `time_format` parameter to `get_channel_message_history()`.

Actually, looking more carefully, the simplest approach is to just handle it in `build_prompt()` -- take the existing `self._message_history` list and format it differently. The history items are already formatted as `[HH:MM:SS] content` strings. FiFi's `build_prompt()` can parse these and convert to delta format, or simply use them as-is (the LLM can understand HH:MM:SS timestamps just fine). The research suggests time deltas are more intuitive for the LLM, but the difference is marginal.

#### Channel-Specific Message History Limit

To get 10 messages instead of 5 for FiFi, the simplest approach is to check the handler name before fetching history in main.py line 551-554:

```python
# Current (line 551-554):
message_history = await self.get_channel_message_history(
    message.channel, limit=5, exclude_message_id=message.id
)

# Could become (checking handler-specific config):
history_limit = CHANNELS_CONFIG.get(handler.name, {}).get("message_history_limit", 5)
message_history = await self.get_channel_message_history(
    message.channel, limit=history_limit, exclude_message_id=message.id
)
```

And add `"message_history_limit": 10` to FiFi's CHANNELS_CONFIG entry.

Alternatively, just increase the global limit to 10 -- extra history does not hurt Sean's parser since it just includes it as additional context.

#### Role Ping Detection

FiFi's alert role ping is `<@&1369304547356311564>`. This string appears in the raw message content. In `build_prompt()`:

```python
has_alert_ping = "<@&1369304547356311564>" in str(self._current_message_meta)
```

For tuples (replies), check both elements. This boolean is then injected into the prompt as context.

#### Edge Cases to Handle

1. **"out of potentially"**: "This is 1st out of potentially 4" is NOT an exit. The prompt's negative constraints should handle this.
2. **"TP 630"**: Ambiguous -- could be a price level, not a trim price. LLM should use position context.
3. **Video recap posts**: Contain "opened" but are recaps. Negative constraint: "Do NOT treat video/recap summaries as trades."
4. **"stops at BE"**: Stop loss management, NOT an exit. Negative constraint required.
5. **"selling 1/2 at .60"**: This is a trim, not STO. The LLM should differentiate based on context.
6. **Mixed trims**: "sold 1/4 MRK here at $2.60 / trim TSLA weekly $3.7" -> two separate trims. LLM should return an array.
7. **Multi-ticker buys**: "Added to April puts\nSPY $670 @ $9.50\nQQQ $600p @ 11.60" -> two buys. LLM should return an array.

#### No `__init__.py` in channels/

The `/Users/mautasimhussain/trading-bots/RHTBv5/channels/` directory has no `__init__.py`. Imports use relative paths within the package (e.g., `from .base_parser import BaseParser`). This is fine -- Python 3 supports implicit namespace packages. No need to create an `__init__.py`.

## User Notes
- Research findings: sessions/tasks/m-research-fifi-channel-parsing.md
- Scraped messages CSV: fifi_messages.csv (1000 messages, 2025-12-16 to 2026-02-04)
- Start as tracking-only (min_trade_contracts=0), no live trading until validated
- FiFi's channel ID: 1368713891072315483
- Old FiFi parser recoverable from git: `git show dc587876cebc59e18b98682dc6d4cffb4852049d~1:channels/fifi.py`

## Work Log
<!-- Updated as work progresses -->
- [2026-02-03] Task created from research findings
