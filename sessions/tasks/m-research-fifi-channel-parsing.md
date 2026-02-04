---
name: m-research-fifi-channel-parsing
branch: none
status: pending
created: 2026-02-03
---

# Research FiFi Channel Alert Parsing

## Problem/Goal
FiFi is a trader specializing in short-term options with a non-standardized, plain-English alerting style. Unlike structured alert channels (e.g., Sean), FiFi's messages are dynamic and conversational - she describes buys/sells in natural language without consistent formatting.

The goal is to:
1. Scrape the last 1000 messages from FiFi's Discord channel (ID: 1368713891072315483)
2. Analyze messaging patterns, structure, and alert types
3. Categorize message types (buy alerts, trim/exit alerts, commentary, etc.)
4. Design a parsing strategy that can extract actionable trade signals from her plain-English posts

## Success Criteria
- [ ] Successfully scrape 1000 messages from FiFi's channel to CSV
- [ ] Produce a categorized analysis of message types and patterns
- [ ] Identify recurring linguistic patterns for buys, trims, exits, and commentary
- [ ] Document a proposed parsing strategy with example mappings (message -> parsed alert)

## Context Manifest
<!-- Added by context-gathering agent -->

### How the Discord Scraper Works

The scraper lives at `/Users/mautasimhussain/trading-bots/IBKR_MES/archive/IBKR_ES/development/discord_scraper.py` and is a standalone Python script built on the `discord.py-self` library (a fork of discord.py that uses user tokens instead of bot tokens for self-bot access). It reads `DISCORD_USER_TOKEN` from a `.env` file via `python-dotenv`.

**Invocation**: The scraper is run from the command line as `python discord_scraper.py <channel_id> <output_file.csv>`. It takes exactly two positional arguments. For this task, the command will be:
```
python discord_scraper.py 1368713891072315483 fifi_messages.csv
```

**Architecture**: The `DiscordScraper` class initializes a bare `discord.Client()` (no intents needed for discord.py-self), registers an `on_ready` event handler, and calls `self.client.start(self.discord_token)` via `asyncio.run()`. Once connected, the `on_ready` handler triggers `scrape_channel()` which fetches messages using `channel.history(limit=self.MAX_MESSAGES)`. Messages arrive newest-first. After scraping, the client auto-closes.

**Current Limit**: The scraper's `MAX_MESSAGES` is hardcoded to **500** on line 27 (`self.MAX_MESSAGES = 500`). This needs to be bumped to **1000** for this task. The relevant line is:
```python
self.MAX_MESSAGES = 500  # Change to 1000
```

**Message Data Captured**: For each message, the scraper captures a comprehensive set of fields (see `parse_message()` method, lines 95-208):
- Core identification: `message_id`, `channel_id`, `channel_name`, `server_id`, `server_name`
- Timestamps: `timestamp` (ISO format), `edited_timestamp`
- Author info: `author_id`, `author_name`, `author_display_name`, `author_is_bot`
- Content: `content` (the raw text), `message_type`, `is_pinned`
- Reply context: `is_reply`, `reply_to_message_id`, `reply_to_author`, `reply_to_content` (truncated to 200 chars)
- Forward info: `is_forward`, `forward_source`
- Embeds: `has_embeds`, `embed_count`, `embed_titles`, `embed_descriptions`, `embed_urls`
- Attachments: `has_attachments`, `attachment_count`, `attachment_names`, `attachment_urls`
- Reactions: `has_reactions`, `reaction_count`, `reactions` (format: "emoji:count | emoji:count")
- Mentions: `mention_count`, `mentioned_users`, `role_mention_count`

**Rate Limiting**: The scraper has a built-in 0.1 second delay between each message (`await asyncio.sleep(0.1)`) and prints a progress indicator every 50 messages.

**Reply Resolution**: When a message is a reply, the scraper calls `channel.fetch_message(message.reference.message_id)` to fetch the original message. This is important for FiFi analysis because replies often contain the action (e.g., "stopped out") while the original contains the trade details. Note this fetch can fail (bare `except:` catches it), yielding "Message not found" placeholders.

**Output Format**: The CSV export uses `csv.DictWriter` with a fixed column order. All fields are stringified. The CSV file uses UTF-8 encoding.

**Environment Requirements**: The scraper needs:
1. `discord.py-self` library installed (NOT regular discord.py -- the self-bot fork)
2. `DISCORD_USER_TOKEN` in a `.env` file (the RHTBv5 project has a `.env` at `/Users/mautasimhussain/trading-bots/RHTBv5/.env` that already contains this token)
3. The user account must have access to FiFi's channel (ID: 1368713891072315483)

**Running the Scraper from RHTBv5**: Since the RHTBv5 `.env` file already has the `DISCORD_USER_TOKEN`, the scraper can either be run from the RHTBv5 directory or the `.env` path can be specified. The simplest approach is to copy the scraper script into the RHTBv5 project or run it from the IBKR_MES directory that also has its own `.env`.

### How the Channel Parser System Works

The bot uses a plugin-based channel parser architecture. Each trader's Discord channel gets its own parser class that inherits from `BaseParser` (`/Users/mautasimhussain/trading-bots/RHTBv5/channels/base_parser.py`). Currently only Sean's channel is active, but the system was designed for multiple channels.

**Parser Registration Flow (main.py)**:

1. `CHANNELS_CONFIG` in `config.py` (lines 106-124) defines each channel with `live_id`, `test_id`, `parser` (class name string), and channel-specific settings (padding, stop loss, model, color, etc.).

2. `main.py` imports parser classes at the top (line 25-26):
```python
from channels.sean import SeanParser
from channels.price_parser import PriceParser
```

3. `ChannelHandlerManager.update_handlers()` (main.py lines 76-94) iterates over `CHANNELS_CONFIG`, looks up each parser class by name using `globals()[parser_class_name]`, instantiates it with the OpenAI client, channel ID, and config, then maps `channel_id -> parser_instance` in `self.handlers`.

4. When a Discord message arrives, `on_message()` (main.py line 543) calls `self.channel_manager.get_handler(message.channel.id)` to find the matching parser. If found, message content is extracted and sent to `trade_executor.process_trade()`.

**To add FiFi's channel back**, one would need to:
- Create a new `channels/fifi.py` with a `FiFiParser` class extending `BaseParser`
- Add `from channels.fifi import FiFiParser` to `main.py`
- Add a `"FiFi"` entry to `CHANNELS_CONFIG` in `config.py`

### BaseParser Architecture (channels/base_parser.py)

This is the 760-line abstract base class that all channel parsers inherit from. Understanding it is critical for designing FiFi's parsing strategy.

**Core Method: `parse_message()`** (lines 424-519):
1. Checks the in-memory response cache (`ParseCache`, 5-minute TTL) for duplicate messages
2. Sets `self._current_message_meta` and `self._message_history` for use in `build_prompt()`
3. Calls `self.build_prompt()` (abstract, implemented by subclass) to get the channel-specific OpenAI prompt
4. Calls `self._call_openai(prompt, logger)` which tries gpt-4o-mini first, then falls back to the configured model (usually gpt-4o)
5. Standardizes action values using `_standardize_action()` which maps many variations ("buy", "entry", "bto", "long", "bought", etc.) to four canonical actions: "buy", "trim", "exit", "null"
6. Calls `_normalize_entry()` (overridable hook for subclass-specific normalization)
7. Validates against Pydantic schemas (`BuyAlert`, `TrimAlert`, `ExitAlert`, `CommentaryAlert`)
8. Caches the result and returns `(normalized_results, latency_ms)`

**Pydantic Alert Schemas** (lines 100-195):
- `BuyAlert`: action="buy", ticker (str), strike (float), type ("call"/"put"), expiration (str, YYYY-MM-DD), price (float), size ("full"/"half"/"lotto")
- `TrimAlert`: action="trim", ticker (str), strike (optional float), type (optional), expiration (optional), price (float or "BE")
- `ExitAlert`: action="exit", ticker (str), strike (optional float), type (optional), expiration (optional), price (float or "BE")
- `CommentaryAlert`: action="null", message (optional str)

**Action Standardization** (lines 241-282): Maps dozens of action word variations:
- Buy: "buy", "entry", "bto", "long", "open", "enter", "bought", "buying", "opening", etc.
- Trim: "trim", "scale", "partial", "reduce", "take", "tp", "half", "some", etc.
- Exit: "exit", "close", "stop", "stc", "sell", "out", "sold", "exiting", "done", "finished", etc.
- Stop loss: "stop_loss", "sl", "stopped_out", "stop_hit" -> maps to "exit"
- Null: "null", "comment", "update", "watching", "hold", "wait", "considering", "maybe", etc.

**OpenAI Call Strategy** (lines 343-399):
- Primary model: gpt-4o-mini (faster, cheaper)
- Fallback: configured model per channel (typically gpt-4o-2024-08-06)
- JSON mode always enabled: `response_format: {"type": "json_object"}`
- Temperature: 0 (deterministic)
- Retry: exponential backoff (1s, 2s, 4s) for transient errors (rate limits, timeouts, 5xx)

**Date Handling** (lines 521-690):
- `_smart_year_detection()`: Converts MM-DD to YYYY-MM-DD; dates in the past roll to next year
- `_parse_monthly_expiration()`: Converts "JAN 2026" etc. to third Friday of that month
- Both are applied as FALLBACK in `_normalize_entry()` if the LLM did not already produce YYYY-MM-DD format

### The Old FiFi Parser (Recovered from Git History)

The previous `FiFiParser` was deleted in commit `dc58787` ("Refactor trading bot to Sean channel only") on 2026-01-27. It was 258 lines and contained FiFi-specific features that are highly relevant for understanding her trading style and parsing needs.

**Key FiFi-Specific Features from the old parser:**

1. **"SOLD TO OPEN" (STO) Pattern**: FiFi frequently uses "SOLD TO OPEN" language for sell-to-open options strategies (e.g., selling puts for premium). The old parser had extensive prompt instructions and a `_normalize_entry()` fallback to detect STO patterns and map them to "exit" actions. It also extracted premium amounts (e.g., "collect $1,030 in premium").

2. **Direct Buy Order Recognition**: FiFi posts buy orders without explicit action words -- just "PLTR $150 put 8/22 $3.40" with no "BTO" or "buying" prefix. The old parser was trained to recognize this pattern.

3. **Enhanced Stop-Out Detection**: Phrases like "stopped out", "got stopped", "we got stopped", "stop hit", "hit my stop" were given special handling to always resolve as "exit".

4. **Embedded Contract Notation Parsing**: FiFi sometimes mashes ticker+strike+type together like "BMNR50p". The `_normalize_entry()` method had regex to parse this (pattern: `^([A-Z]+)(\d+(?:\.\d+)?)(c|p|call|put)$`).

5. **Date Handling**: The old parser did NOT convert dates to YYYY-MM-DD in the prompt -- it asked the LLM to return raw expiration text (e.g., "1/16", "Sep 19", "0dte"). The BaseParser's `_normalize_entry()` fallback then handled the conversion. This is different from Sean's parser which asks the LLM to convert dates directly.

6. **Default 0DTE**: If no expiration was found for a buy order, the old parser defaulted to today's date (0DTE).

7. **Size Normalization**: Non-standard sizes ("some", "small", "starter") mapped to "half"; ("tiny", "lotto") mapped to "lotto".

**Old FiFi Channel Config** (recovered from git):
```python
"FiFi": {
    "live_id": 1368713891072315483,
    "test_id": 1402850612995031090,
    "parser": "FiFiParser",
    "multiplier": 1.0,
    "min_trade_contracts": 0,  # Was tracking-only (0 means no actual trading)
    "initial_stop_loss": 0.50,
    "trailing_stop_loss_pct": 0.20,
    "buy_padding": 0.025,
    "sell_padding": 0.01,
    "model": "gpt-4o-2024-08-06",
    "color": 15277667,  # Pink
    "description": "FiFi's swing and momentum trades",
    "risk_level": "medium",
    "typical_hold_time": "30 minutes - 4 hours",
    "trade_first_mode": True
}
```

Note: `min_trade_contracts: 0` meant this channel was in tracking-only mode -- parsing and logging alerts without executing trades. This is important context: the previous implementation was primarily for monitoring/research, not live trading.

### How Sean's Parser Works (for comparison)

The `SeanParser` at `/Users/mautasimhussain/trading-bots/RHTBv5/channels/sean.py` (184 lines) is the simplest reference for how a channel parser should be structured.

**Structure**: Extends `BaseParser`, has `__init__` calling `super().__init__()`, and overrides only `build_prompt()`. It does NOT override `_normalize_entry()` (uses the base class default which just handles date fallback).

**Prompt Design**: The prompt includes:
- Dynamic date injection (today's date, current year) for date conversion in the LLM
- Message context handling (PRIMARY + ORIGINAL for replies)
- Action definitions with strict "buy"/"trim"/"exit"/"null" vocabulary
- Date rules asking the LLM to convert all dates to YYYY-MM-DD directly
- Size rules ("half", "lotto", "full")
- Weekly trade plan filtering (return null)
- Portfolio update filtering (return null)
- Multiple few-shot examples for each action type
- Message history injection for conversation context

**Key Difference from FiFi**: Sean's alerts tend to follow more standardized patterns like "$SPY 580c 0dte @ 1.50" while FiFi uses conversational plain-English. This means FiFi's parser will need:
- More sophisticated LLM prompt engineering with more edge-case examples
- Potentially heavier reliance on `_normalize_entry()` for post-processing
- Better handling of implicit/unstated information

### Trade Execution Flow (What Happens After Parsing)

After a parser returns parsed results, the flow continues in `trade_executor.py`:

1. `process_trade()` (line 364) receives the handler, message metadata, and sim mode flag
2. Calls `handler.parse_message()` to get parsed results
3. For each parsed result:
   - `_normalize_keys()` standardizes key names
   - For trim/exit actions: tries to resolve the target position via:
     a. Position ledger (`resolve_position()` with weighted scoring)
     b. Position manager (`find_position()`)
     c. Performance tracker (`find_open_trade_by_ticker()`)
     d. Feedback CSV fallback (`get_recent_parse_for_channel()`)
     e. Robinhood API fallback (`get_contract_info_for_ticker()`)
   - Symbol mapping applied (e.g., SPX -> SPXW)
   - Trade executed via `_execute_buy_order()` or `_execute_sell_order()`
   - Position tracking updated

This resolution chain is important because FiFi's trim/exit alerts often lack contract details (just "stopped out of PLTR"), so the system must resolve the specific contract from tracked positions. The position ledger and feedback CSV are the primary resolution mechanisms.

### What the Research Task Needs to Produce

This task is purely research/analysis. No code changes to the trading bot are expected. The deliverables are:

1. **Scraped CSV**: Run the discord scraper with `MAX_MESSAGES=1000` against channel ID `1368713891072315483`, outputting to a CSV file (suggested: `/Users/mautasimhussain/trading-bots/RHTBv5/fifi_messages.csv` or a `data/` subdirectory).

2. **Message Pattern Analysis**: Read through the scraped messages and categorize them into:
   - Buy alerts (with various formats FiFi uses)
   - Trim alerts
   - Exit alerts (including stopped-out, STO patterns)
   - Commentary/non-actionable messages
   - Any new patterns not covered by the old parser

3. **Linguistic Pattern Catalog**: Document recurring phrases, structures, and conventions FiFi uses for each alert type. Example mappings like "FiFi says X -> parsed as Y".

4. **Proposed Parsing Strategy**: Based on patterns found, recommend:
   - Whether the old FiFiParser approach is still valid or needs redesign
   - New patterns to handle
   - LLM prompt improvements
   - `_normalize_entry()` post-processing rules
   - Edge cases and ambiguity resolution strategies

### Technical Reference Details

#### Discord Scraper

- **File**: `/Users/mautasimhussain/trading-bots/IBKR_MES/archive/IBKR_ES/development/discord_scraper.py`
- **Key modification needed**: Line 27 -- change `self.MAX_MESSAGES = 500` to `self.MAX_MESSAGES = 1000`
- **Invocation**: `python discord_scraper.py 1368713891072315483 fifi_messages.csv`
- **Dependencies**: `discord.py-self`, `python-dotenv`
- **Auth**: `DISCORD_USER_TOKEN` from `.env` file

#### Channel Parser System

- **Base parser**: `/Users/mautasimhussain/trading-bots/RHTBv5/channels/base_parser.py` (760 lines)
- **Sean parser (reference)**: `/Users/mautasimhussain/trading-bots/RHTBv5/channels/sean.py` (184 lines)
- **Price parser (utility, not trade)**: `/Users/mautasimhussain/trading-bots/RHTBv5/channels/price_parser.py` (127 lines)
- **No `__init__.py`**: The channels directory has no `__init__.py`; imports use direct module paths

#### Alert Schemas (for reference when analyzing FiFi messages)

```python
# BuyAlert required fields:
{"action": "buy", "ticker": "SPY", "strike": 580.0, "type": "call", "expiration": "2026-02-03", "price": 1.50, "size": "full"}

# TrimAlert required fields (strike/type/expiration optional -- resolved from position):
{"action": "trim", "ticker": "SPY", "price": 2.30}

# ExitAlert required fields (strike/type/expiration optional -- resolved from position):
{"action": "exit", "ticker": "SPY", "price": 12.50}
# Exit with no price: {"action": "exit", "ticker": "SPY", "price": "market"}
# Exit at breakeven: {"action": "exit", "ticker": "SPY", "price": "BE"}
```

#### FiFi Channel Details

- **Live Channel ID**: 1368713891072315483
- **Test Channel ID** (from old config): 1402850612995031090
- **Trader style**: Short-term options, swing and momentum trades, 30 min to 4 hours typical hold time
- **Risk level**: Medium
- **Known special patterns**: SOLD TO OPEN, direct order notation (no action word), embedded ticker+strike+type, premium collection language

#### Configuration Values (for eventual re-integration)

```python
# From old CHANNELS_CONFIG entry:
"FiFi": {
    "live_id": 1368713891072315483,
    "test_id": 1402850612995031090,
    "parser": "FiFiParser",
    "multiplier": 1.0,
    "min_trade_contracts": 0,  # 0 = tracking only, bump to 2+ for live trading
    "initial_stop_loss": 0.50,
    "trailing_stop_loss_pct": 0.20,
    "buy_padding": 0.025,
    "sell_padding": 0.01,
    "model": "gpt-4o-2024-08-06",
    "color": 15277667,  # Pink
    "description": "FiFi's swing and momentum trades",
    "risk_level": "medium",
    "typical_hold_time": "30 minutes - 4 hours",
    "trade_first_mode": True
}
```

#### File Locations Summary

- Scraper script: `/Users/mautasimhussain/trading-bots/IBKR_MES/archive/IBKR_ES/development/discord_scraper.py`
- RHTBv5 .env (has DISCORD_USER_TOKEN): `/Users/mautasimhussain/trading-bots/RHTBv5/.env`
- Config: `/Users/mautasimhussain/trading-bots/RHTBv5/config.py`
- Base parser: `/Users/mautasimhussain/trading-bots/RHTBv5/channels/base_parser.py`
- Sean parser (reference): `/Users/mautasimhussain/trading-bots/RHTBv5/channels/sean.py`
- Main bot: `/Users/mautasimhussain/trading-bots/RHTBv5/main.py`
- Trade executor: `/Users/mautasimhussain/trading-bots/RHTBv5/trade_executor.py`
- Old FiFi parser (git): `git show dc587876cebc59e18b98682dc6d4cffb4852049d~1:channels/fifi.py`
- Output CSV (suggested): `/Users/mautasimhussain/trading-bots/RHTBv5/fifi_messages.csv`

## User Notes
- FiFi's channel ID: 1368713891072315483
- Reference scraper: /Users/mautasimhussain/trading-bots/IBKR_MES/archive/IBKR_ES/development/discord_scraper.py
- Scraper uses discord.py-self with DISCORD_USER_TOKEN from .env
- Existing scraper fetches 500 messages; needs bump to 1000 for this task

## Work Log
<!-- Updated as work progresses -->
- [2026-02-03] Task created
