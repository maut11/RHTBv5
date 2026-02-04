---
name: m-research-fifi-channel-parsing
branch: main
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
- [x] Successfully scrape 1000 messages from FiFi's channel to CSV
- [x] Produce a categorized analysis of message types and patterns
- [x] Identify recurring linguistic patterns for buys, trims, exits, and commentary
- [x] Document a proposed parsing strategy with example mappings (message -> parsed alert)

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

## Research Findings

### Data Overview

- **Scraped**: 1000 messages from #fifi-alerts (2025-12-16 to 2026-02-04)
- **FiFi's username**: `sauced2002` (995 of 1000 messages)
- **Alert role ping**: `<@&1369304547356311564>` (appended to actionable messages)
- **CSV output**: `/Users/mautasimhussain/trading-bots/RHTBv5/fifi_messages.csv`

### Message Distribution

| Category | Count | % | Actionable? |
|---|---|---|---|
| Buy entries | 55 | 5.5% | Yes |
| Implicit buys (no action word) | 4 | 0.4% | Yes |
| Add to position | 12 | 1.2% | Yes (treat as buy) |
| Trims | 154 | 15.5% | Yes |
| Exits | 73 | 7.3% | Yes |
| Trim summaries | 20 | 2.0% | No (recap) |
| Limit order announcements | 8 | 0.8% | No (pending) |
| Watchlist/forward-looking | 26 | 2.6% | No |
| Recaps | 2 | 0.2% | No |
| Commentary | 571 | 57.4% | No |
| Ping/emoji only | 70 | 7.0% | No |

**Actionable: 298 messages (29.9%)** | Non-actionable: 697 (70.1%)

### Linguistic Pattern Catalog

#### BUY Patterns

**Format 1: "in TICKER" prefix** (most common ~60% of buys)
```
"in PLTR 2/6 $155p $2.70"           -> buy PLTR 2026-02-06 155 put @ 2.70
"in MO 0dte $61c .08"               -> buy MO today 61 call @ 0.08
"in QQQ 0dte 615p 1/8 size .88"     -> buy QQQ today 615 put @ 0.88 (half)
"in TSLA 2/20 $400p $6.80"          -> buy TSLA 2026-02-20 400 put @ 6.80
"in UPS March $115c @ $2"           -> buy UPS March-20 115 call @ 2.00
"in XOM weekly 134c .82"            -> buy XOM weekly 134 call @ 0.82
"in SLV 0dte 80p .18"              -> buy SLV today 80 put @ 0.18
```

**Format 2: "scaling into" / "bought"**
```
"scaling into XOM March 20 $140c $4.30 bought 1/4 size"
"Bought a starter size 1/5 position in both:
 SPY 2/20 $680p @ $5.92
 QQQ 3/20 $600p @ $9.72"           -> 2 buys (multi-ticker)
```

**Format 3: "grabbed"**
```
"grabbed a couple 180p weekly .31"   -> buy [context-ticker] weekly 180 put @ 0.31
"Grabbed some IWM Odte 260p .31"    -> buy IWM today 260 put @ 0.31
```

**Format 4: Implicit buy (no action word)**
```
"TSLA 480p 0dte 1.40"              -> buy TSLA today 480 put @ 1.40
"XOM 130c 0dte at .25"             -> buy XOM today 130 call @ 0.25
"short QQQ 613p 0dte .47"          -> buy QQQ today 613 put @ 0.47
```

**Format 5: "added" (average into position)**
```
"added full size into MRK 2/20 $110c here at $2.90"
"added 1/2 size SMH 1/30 $390p $6.15"
"added XOM $135c 2/20 $2"
"added to NVDA here .53 new average is .82"  -> buy [resolve from position] @ 0.53
```

**Format 6: Multi-line**
```
"in PLTR 2/6
$155p $2.70
SL is HOD"
```

**Format 7: Multi-ticker buy**
```
"Added to April puts
SPY $670 @ $9.50
QQQ $600p @ 11.60"                 -> 2 buys
```

#### TRIM Patterns

**Format 1: "trim $PRICE" (reply-based, most common)**
```
"trim .18"                          -> trim [resolve from reply] @ 0.18
"trim .35"                          -> trim [resolve from reply] @ 0.35
"trim $9.50"                        -> trim [resolve from reply] @ 9.50
```
Reply contains the original buy with full contract details.

**Format 2: "trim TICKER $PRICE"**
```
"Trim spy weekly $7"                -> trim SPY weekly @ 7.00
"trim XOM $4.1"                     -> trim XOM @ 4.10
"trim QQQ puts at 3.20 from .43"    -> trim QQQ @ 3.20
"trim XOM feb 135c $2.80 from $2"   -> trim XOM 2/20 135 call @ 2.80
```

**Format 3: "Trimmed TICKER $PRICE from $ENTRY"**
```
"Trimmed spy 7.20 from 4.60 for 2/20"     -> trim SPY 2/20 @ 7.20
"Trimmed QQQ 2/20 at $10.60 from 6.60"    -> trim QQQ 2/20 @ 10.60
"Trimmed XOM 7.5"                          -> trim XOM @ 7.50
```

**Format 4: "sold X here/at $PRICE"**
```
"Sold some more XOM 6.50"          -> trim XOM @ 6.50
"sold 1/4 here .40"                -> trim [resolve from reply] @ 0.40
"sold 1/2 SLV here .20 +100%"      -> trim SLV @ 0.20
```

**Format 5: "TP $PRICE"**
```
"TP 630"                            -> trim [resolve from context]
```

#### EXIT Patterns

**Format 1: "out TICKER $PRICE" (most common)**
```
"out TSLA 1.4"                      -> exit TSLA @ 1.40
"out pltr lotto .16"                -> exit PLTR @ 0.16
"out last piece of MRK 3.20"       -> exit MRK @ 3.20
```

**Format 2: "Out TICKER BE"**
```
"Out PLTR BE here"                  -> exit PLTR @ BE
"out rest BE of MO"                 -> exit MO @ BE
"out WMT BE"                        -> exit WMT @ BE
```

**Format 3: "all out TICKER"**
```
"all out SNDK for now"              -> exit SNDK @ market
"all out of NUE $6.90"             -> exit NUE @ 6.90
```

**Format 4: Multi-ticker exit**
```
"Out nvda 1.50 from 2.5
Out spy 4.10 from 5.5"             -> exit NVDA @ 1.50 + exit SPY @ 4.10
```

**Format 5: Stopped out**
```
"got stopped on rest of RGTI"      -> exit RGTI @ market
"stopped out BE on AAPL, QQQ"      -> exit AAPL @ BE + exit QQQ @ BE
```

#### NON-ACTIONABLE Patterns (must return null)

- **Trim summaries**: Posts with haircut emoji listing entry->exit prices (already executed)
- **Open Positions lists**: Posts with "FiFi's Open Positions" and bullet points
- **Limit order announcements**: "have a limit sell in for..."
- **Watchlist**: "eyeing", "watching", "looking to"
- **SL declarations**: "SL is HOD/LOD/close over $X"
- **Emoji/ping only**: Just role mentions or emoji reactions

### Critical: Reply Context

**50 of 298 actionable messages (16.8%)** use reply-based context. The trim/exit has minimal info (just a price) and relies on the replied-to message for contract details. The parser MUST inject reply context into the LLM prompt.

### No STO Pattern Detected

Zero "Sold to Open" messages in the last 1000 messages. Keep minimal handling but deprioritize.

### Reference Tables

**Price formats**: $X.XX (178), $X (189), .XX (common sub-dollar), X.XX no $ (105), @ $X (44), at $X (49), BE (46)

**Expiration formats**: M/D (161), weekly (65), 0dte (48), Full month (24), Month abbrev (13)

**Size mapping**: 1/4->half, 1/2->half, full->full, lotto->lotto, starter->half, 1/8->lotto, couple cons->half, SUPER SMALL->lotto

## Proposed Parsing Strategy

### Recommendation: Rebuild FiFiParser with enhanced LLM prompt

The old parser's architecture is **still valid**. Use `BaseParser` + `build_prompt()` + custom `_normalize_entry()`.

### Key Design Decisions

1. **Primary model**: gpt-4o-mini with gpt-4o fallback
2. **Reply context is critical**: Inject PRIMARY + ORIGINAL messages. 16.8% of signals depend on this.
3. **Trim summaries must return null**: Explicitly instruct LLM to ignore haircut-emoji recap posts
4. **Multi-ticker messages**: LLM returns array of alerts for multi-trade messages
5. **STO handling**: Minimal - zero occurrences in recent data

### Core Parser Enhancements (Approved)

**1. Ledger injection into prompt** (highest impact)
- Inject compact JSON of open FiFi-channel positions into system prompt
- Format: `OPEN POSITIONS: [{ticker, strike, type, exp, avg_cost}]`
- Enables LLM to resolve ambiguous trims/exits ("trim $7" -> which position?)
- Read from `PositionLedger` at parse time, filter to FiFi channel positions

**2. Reply context with clear tags**
- Inject replied-to message: `PRIMARY: [message]` / `REPLYING TO: [original]`
- Covers 16.8% of actionable signals that are reply-based
- Already wired in bot's `on_message()`, just needs prompt formatting

**3. Last 10 messages with time deltas**
- Expand history from 5 (Sean default) to 10 for FiFi
- Prepend time delta tags: `[2m ago]`, `[15m ago]`
- FiFi's conversational style means trims may reference buys 8-10 messages back

**4. Negative constraint firewall**
- Explicit "Do NOT" rules in prompt:
  - Do NOT treat "watching"/"eyeing"/"looking to" as entries
  - Do NOT treat trim summaries (haircut emoji + entry->exit lists) as live trades
  - Do NOT treat "have a limit sell" as executed trades
  - Do NOT treat "SL is HOD/LOD" or "stops at BE" as exits
  - Do NOT treat open positions lists as trades

**5. Role ping as signal**
- Pass `has_alert_ping: true/false` to the prompt
- Messages WITH the role ping have higher probability of being actionable
- Not a hard filter, but a probability weight for the LLM

### Prompt Design

The `build_prompt()` should include:
1. Action definitions with FiFi-specific vocabulary
2. Reply context injection (PRIMARY + ORIGINAL)
3. Open positions from ledger (compact JSON)
4. Last 10 messages with time deltas
5. Negative constraint firewall (explicit "Do NOT" rules)
6. Role ping flag (has_alert_ping)
7. Null rules for summaries, positions lists, limit orders, watchlist, SL declarations
8. Price extraction rules ($X.XX, .XX, X.XX, "BE", "market")
9. Expiration conversion (0dte->today, weekly->Friday, M/D->YYYY-MM-DD)
10. Size mapping table
11. Multi-ticker handling instructions
12. 8-10 few-shot examples from real messages

### `_normalize_entry()` Post-Processing

1. Embedded contract notation regex: `^([A-Z]+)(\d+(?:\.\d+)?)(c|p)$`
2. "from $X" stripping (extract current price only)
3. Size normalization (1/4, 1/8, starter, couple -> schema values)
4. Default 0DTE when action=buy and no expiration
5. "rest"/"runners" in exits -> full exit

### Example Mappings

| FiFi Message | Parsed Alert |
|---|---|
| `in PLTR 2/6 $155p $2.70 SL is HOD` | `{action:"buy", ticker:"PLTR", strike:155, type:"put", exp:"2026-02-06", price:2.70, size:"full"}` |
| `in MO 0dte $61c .08 LOTTO SIZE` | `{action:"buy", ticker:"MO", strike:61, type:"call", exp:"today", price:0.08, size:"lotto"}` |
| `TSLA 480p 0dte 1.40` | `{action:"buy", ticker:"TSLA", strike:480, type:"put", exp:"today", price:1.40, size:"full"}` |
| `trim .18 +100%` (reply to MO buy) | `{action:"trim", ticker:"MO", price:0.18}` |
| `Trimmed spy 7.20 from 4.60 for 2/20` | `{action:"trim", ticker:"SPY", price:7.20}` |
| `Out PLTR BE here` | `{action:"exit", ticker:"PLTR", price:"BE"}` |
| `all out SNDK for now` | `{action:"exit", ticker:"SNDK", price:"market"}` |
| `stopped out BE on AAPL, QQQ` | `[exit AAPL @ BE, exit QQQ @ BE]` |
| Trim summary with haircut emoji | `{action:"null"}` |
| `Eyeing SMH short on the next bounce` | `{action:"null"}` |

### Edge Cases

1. **"out of potentially"** - NOT an exit ("This is 1st out of potentially 4")
2. **"TP 630"** - Ambiguous price, LLM should infer from option range
3. **Video recap posts** - Contain "opened" but are recaps, not trades
4. **"stops at BE"** - SL management, not an exit action
5. **"selling 1/2 at .60"** - Trim, not STO
6. **Mixed trims** - "sold 1/4 MRK here at $2.60 / trim TSLA weekly $3.7" -> two trims

## User Notes
- FiFi's channel ID: 1368713891072315483
- Reference scraper: /Users/mautasimhussain/trading-bots/IBKR_MES/archive/IBKR_ES/development/discord_scraper.py
- Scraper uses discord.py-self with DISCORD_USER_TOKEN from .env
- Existing scraper fetches 500 messages; needs bump to 1000 for this task

## Work Log
<!-- Updated as work progresses -->
- [2026-02-03] Task created
- [2026-02-03] Scraped 1000 messages from FiFi's channel (2025-12-16 to 2026-02-04)
- [2026-02-03] Completed message classification: 298 actionable (29.9%), 697 non-actionable (70.1%)
- [2026-02-03] Documented linguistic patterns for all alert types with examples
- [2026-02-03] Proposed parsing strategy: rebuild FiFiParser using BaseParser architecture
- [2026-02-03] Key finding: 16.8% of actionable signals are reply-based (need reply context)
- [2026-02-03] Key finding: zero STO patterns in recent data (deprioritize)
- [2026-02-03] Key finding: trim summaries and position lists must be filtered as null
