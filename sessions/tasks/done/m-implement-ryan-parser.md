---
name: m-implement-ryan-parser
branch: feature/implement-ryan-parser
status: complete
created: 2026-02-03
---

# Implement Ryan Channel Parser

## Problem/Goal
Build a `RyanParser` class to parse Ryan's 0DTE SPX options alerts from Discord embeds. Ryan's alerts arrive as structured embeds from "Sir Goldman Alert Bot" with title-based action dispatch (ENTRY/TRIM/EXIT/COMMENT). Unlike Sean and FiFi who use LLM parsing, Ryan's parser should be **regex-based for lowest latency** — no OpenAI call for ENTRY/TRIM/EXIT.

## Research Context

### Ryan's Embed Structure (from IBKR_SPX `core/ryan_parser.py`)
- **Source bot**: "Sir Goldman Alert Bot" sends embeds, not plain text
- **Embed title**: "ENTRY" | "TRIM" | "EXIT" | "COMMENT"
- **Embed description**: Actual message text wrapped in `**bold**` markers
- **Embed colors**: green=ENTRY(3066993), yellow=TRIM(16705372), red=EXIT(15158332), blue=COMMENT(3447003)
- **Embed fields**: Always empty

### Parsing Strategy (hybrid, from IBKR_SPX)
- **ENTRY** → Regex on description: `\$SPX\s+(\d+)(p|c)\s*@\s*\$?([\d.]+)` → strike, type, price
- **TRIM** → Title alone triggers action (no description parsing needed)
- **EXIT** → Title alone triggers action (no description parsing needed)
- **COMMENT** → Return null (WATCHING commands not relevant for RHTBv5)
- **Futures filter**: `(?:Long|Short)\s+\$?(?:NQ|GC|ES|CL|YM)` → ignore non-SPX entries

### RHTBv5 Infrastructure Already Available
- `main.py:689` — Embeds with titles already returned as `(embed_title, embed_desc)` tuple in `message_meta`
- `config.py:48` — SPX→SPXW symbol mapping exists
- `trader.py:423-430` — CBOE SPXW tick sizes already implemented ($0.05 under $5, $0.10 over $5)
- `trader.py:590-630` — `round_to_tick()` with buy-up/sell-nearest logic
- Trade-first mode and per-channel min_trade_contracts already wired

### CBOE Pricing Compliance (already in trader.py)
- SPXW < $3.00: $0.05 tick
- SPXW $3.00-$5.00: $0.05 tick
- SPXW > $5.00: $0.10 tick

## Changes Implemented

1. Created `channels/ryan.py` -- RyanParser with regex-based `parse_message()` override
2. Updated `config.py` -- Added Ryan to CHANNELS_CONFIG (multiplier=0.5, min_trade_contracts=1, message_history_limit=0)
3. Updated `main.py` -- Added `from channels.ryan import RyanParser` import
4. Futures filtering via regex pre-check blocks NQ/GC/ES/CL/YM entries

## Success Criteria
- [x] Create `channels/ryan.py` with regex-based RyanParser extending BaseParser
- [x] Ryan added to CHANNELS_CONFIG with 5% portfolio sizing, min 1 contract
- [x] RyanParser imported in main.py
- [x] ENTRY parsed via regex (no LLM call) — extracts strike, type, price, ticker=SPX, exp=today
- [x] TRIM/EXIT dispatched from title only — no description parsing
- [x] COMMENT/unknown embeds return null
- [x] Futures entries ($NQ, $GC, $ES, $CL, $YM) filtered out
- [x] SPX→SPXW symbol mapping verified working for Ryan trades
- [x] CBOE tick size compliance verified (existing trader.py logic)
- [x] Bot starts successfully with Ryan channel registered
- [x] Test against sample Ryan embed messages

## User Notes
- Ryan does 0DTE SPX options only
- Alerts are Discord embeds (title + description), not plain text
- Regex parsing for ENTRY, title-only for TRIM/EXIT — prioritize lowest latency
- 5% of total portfolio per trade, minimum 1 contract
- Ryan live channel: 1072559822366576780
- Ryan sim channel: 1468487671893721233
- Reference implementation: `/Users/mautasimhussain/trading-bots/IBKR_SPX/core/ryan_parser.py`

## Context Manifest

### Architecture Summary (post-implementation)

`RyanParser` (`channels/ryan.py`, 155 lines) extends `BaseParser` but overrides `parse_message()` entirely to bypass LLM. This is architecturally distinct from `SeanParser` and `FiFiParser` which use `build_prompt()` and rely on the base class LLM flow.

**Key design points:**
- Embed `message_meta` arrives as `(embed_title, embed_desc)` tuple from `_extract_message_content()`
- Title-based dispatch: ENTRY -> regex, TRIM/EXIT -> title-only, COMMENT -> null
- Parser sets `ticker="SPX"`; downstream `get_broker_symbol()` maps to `"SPXW"`
- CBOE tick sizes handled automatically by `trader.py` (`round_to_tick()`)
- Position sizing: 10% max * 0.5 multiplier = 5% portfolio per trade
- Cache integration via `get_parse_cache()` from `base_parser`
- Handles own metadata injection (`channel_id`, `received_ts`) since base class is bypassed

**Regex patterns (from IBKR reference):**
- Entry: `\$SPX\s+(\d+)(p|c)\s*@\s*\$?([\d.]+)` -- captures strike, type, price
- Futures filter: `(?:Long|Short)\s+\$?(?:NQ|GC|ES|CL|YM)` -- blocks non-SPX

**Files:**
- `channels/ryan.py` -- parser implementation
- `config.py` -- Ryan added to CHANNELS_CONFIG
- `main.py` -- `from channels.ryan import RyanParser`

## Work Log

### 2026-02-03

#### Completed
- Created `channels/ryan.py` (155 lines) with `RyanParser` extending `BaseParser`
- Overrides `parse_message()` entirely to bypass LLM -- regex-based dispatch for lowest latency
- ENTRY regex: `\$SPX\s+(\d+)(p|c)\s*@\s*\$?([\d.]+)` -- extracts strike, type, price
- TRIM/EXIT: title-only dispatch, no description parsing needed
- COMMENT: returns empty (not actionable for RHTBv5)
- Futures filter regex: `(?:Long|Short)\s+\$?(?:NQ|GC|ES|CL|YM)` -- blocks non-SPX entries
- Description cleaning: strips `**` bold markers, emojis, collapses whitespace
- Cache integration via `get_parse_cache()` from `base_parser`
- Added Ryan to `CHANNELS_CONFIG` in `config.py` (live_id=1072559822366576780, test_id=1468487671893721233, multiplier=0.5, min_trade_contracts=1)
- Added `RyanParser` import in `main.py`
- All 12 validation tests passed: ENTRY put/call, futures filtering NQ/ES, TRIM, EXIT, COMMENT->null, plain text->skip, description cleaning, metadata injection, cache hit
- Latency: 0.0-0.1ms for regex parsing (vs ~700ms for LLM parsers)
- Code review: 0 critical issues, 2 low-risk warnings (dead color fallback, reply-embed edge case)

#### Decisions
- Override `parse_message()` instead of `build_prompt()` to bypass LLM entirely for lowest latency
- Set `price="market"` for TRIM/EXIT since Ryan's embeds do not include exit prices
- Keep color fallback code as dead code (acknowledged inline) for potential future use
- Set `message_history_limit=0` since embeds are self-contained

#### Files Changed
- `channels/ryan.py` -- new file (155 lines)
- `config.py` -- added Ryan to CHANNELS_CONFIG
- `main.py` -- added `from channels.ryan import RyanParser`
