---
name: m-implement-ryan-parser
branch: feature/implement-ryan-parser
status: pending
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

## Changes Required

### 1. Create `channels/ryan.py` — RyanParser class
- Extend `BaseParser` but **override `parse_message()`** to bypass LLM
- Title-based dispatch: ENTRY→regex, TRIM/EXIT→title-only, COMMENT→null
- Entry regex from IBKR_SPX: `\$SPX\s+(\d+)(p|c)\s*@\s*\$?([\d.]+)`
- Futures filter regex: `(?:Long|Short)\s+\$?(?:NQ|GC|ES|CL|YM)`
- Clean description (strip `**` bold markers, emojis, collapse whitespace)
- Always set ticker="SPX" (mapped to SPXW by existing symbol mapping)
- Always set expiration=today (0DTE only)
- Always set type from regex group (c→call, p→put)
- Return standard trade dict format compatible with trade_executor.py

### 2. Update `config.py` — Add Ryan to CHANNELS_CONFIG
- live_id: 1072559822366576780
- test_id: 1468487671893721233
- multiplier: 0.5 (5% portfolio)
- min_trade_contracts: 1
- model: "gpt-4o-mini" (only for COMMENT fallback, not used in hot path)
- trade_first_mode: True
- message_history_limit: 0 (embeds are self-contained)

### 3. Update `main.py` — Import and wire RyanParser
- Add `from channels.ryan import RyanParser`
- Ryan will flow through existing `_extract_message_content()` which already handles embeds

### 4. Filter for SPX calls/puts only (not futures)
- Futures entries have pattern: `Long $NQ ...` or `Short $ES ...`
- Regex pre-check filters these before SPX regex runs
- Only `$SPX {strike}{c|p} @ {price}` pattern passes

## Success Criteria
- [ ] Create `channels/ryan.py` with regex-based RyanParser extending BaseParser
- [ ] Ryan added to CHANNELS_CONFIG with 5% portfolio sizing, min 1 contract
- [ ] RyanParser imported in main.py
- [ ] ENTRY parsed via regex (no LLM call) — extracts strike, type, price, ticker=SPX, exp=today
- [ ] TRIM/EXIT dispatched from title only — no description parsing
- [ ] COMMENT/unknown embeds return null
- [ ] Futures entries ($NQ, $GC, $ES, $CL, $YM) filtered out
- [ ] SPX→SPXW symbol mapping verified working for Ryan trades
- [ ] CBOE tick size compliance verified (existing trader.py logic)
- [ ] Bot starts successfully with Ryan channel registered
- [ ] Test against sample Ryan embed messages

## User Notes
- Ryan does 0DTE SPX options only
- Alerts are Discord embeds (title + description), not plain text
- Regex parsing for ENTRY, title-only for TRIM/EXIT — prioritize lowest latency
- 5% of total portfolio per trade, minimum 1 contract
- Ryan live channel: 1072559822366576780
- Ryan sim channel: 1468487671893721233
- Reference implementation: `/Users/mautasimhussain/trading-bots/IBKR_SPX/core/ryan_parser.py`

## Work Log
<!-- Updated as work progresses -->
