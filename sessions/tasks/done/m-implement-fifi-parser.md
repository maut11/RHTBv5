---
name: m-implement-fifi-parser
branch: feature/implement-fifi-parser
status: complete
created: 2026-02-03
---

# Implement FiFi Channel Parser

## Problem/Goal
Build a `FiFiParser` class to parse FiFi's (sauced2002) plain-English Discord trading alerts into structured trade signals. FiFi's messaging style is conversational and non-standardized, requiring enhanced LLM prompting and position-aware context injection.

Based on research from `m-research-fifi-channel-parsing`, which analyzed 1000 messages and identified all linguistic patterns, message distribution (29.9% actionable), and 5 approved core enhancements.

## Success Criteria
- [x] Create `channels/fifi.py` with `FiFiParser` extending `BaseParser`
- [x] Add FiFi to `CHANNELS_CONFIG` in `config.py` (tracking-only: min_trade_contracts=0)
- [x] Add `FiFiParser` import to `main.py`
- [x] Implement `build_prompt()` with all 5 approved enhancements:
  - [x] Position ledger injection (open positions as compact JSON in prompt)
  - [x] Reply context with clear PRIMARY/REPLYING TO tags
  - [x] Last 10 messages with time deltas
  - [x] Negative constraint firewall (Do NOT rules)
  - [x] Role ping signal (has_alert_ping flag)
- [x] Implement custom `_normalize_entry()` for FiFi-specific post-processing
- [x] Include 8-10 few-shot examples from real FiFi messages
- [x] Bot starts successfully with FiFi channel registered
- [x] Test parse against 10+ real FiFi messages with correct classification

## Context Manifest

### Implementation Summary

FiFiParser (`channels/fifi.py`, 306 lines) extends `BaseParser` with all 5 approved enhancements from the research task. Position ledger access was wired through the parser infrastructure by adding an optional `position_ledger` parameter to `BaseParser.__init__`, `ChannelHandlerManager.__init__`, and the parser instantiation call in `update_handlers()`.

### Files Created
- `/Users/mautasimhussain/trading-bots/RHTBv5/channels/fifi.py` -- FiFiParser class

### Files Modified
- `/Users/mautasimhussain/trading-bots/RHTBv5/config.py` -- Added FiFi to CHANNELS_CONFIG (tracking-only: min_trade_contracts=0), added configurable `message_history_limit` per channel
- `/Users/mautasimhussain/trading-bots/RHTBv5/main.py` -- Added FiFiParser import, wired position_ledger to ChannelHandlerManager, uses per-channel message_history_limit from config
- `/Users/mautasimhussain/trading-bots/RHTBv5/channels/base_parser.py` -- Added optional `position_ledger=None` parameter to `__init__` (backward compatible with SeanParser)
- `/Users/mautasimhussain/trading-bots/RHTBv5/channels/sean.py` -- Updated constructor to pass through position_ledger kwarg

### Key Design Decisions
- Position ledger injection uses Option A (clean infrastructure pass-through, not config dict hack)
- Message history limit is configurable per channel via `message_history_limit` in CHANNELS_CONFIG (FiFi=10, Sean default=5)
- Time delta formatting handled in `build_prompt()` rather than modifying shared `get_channel_message_history()`
- Role ping detection checks for `<@&1369304547356311564>` in message content

### Research Reference
- Research findings: `sessions/tasks/m-research-fifi-channel-parsing.md`
- Scraped messages CSV: `fifi_messages.csv` (1000 messages, 2025-12-16 to 2026-02-04)
- Old parser recoverable from git: `git show dc587876cebc59e18b98682dc6d4cffb4852049d~1:channels/fifi.py`

## User Notes
- Start as tracking-only (min_trade_contracts=0), no live trading until validated
- FiFi's channel ID: 1368713891072315483

## Work Log

### 2026-02-03

#### Completed
- Created `channels/fifi.py` (306 lines) with FiFiParser extending BaseParser
- Wired position ledger through parser infrastructure: `base_parser.py`, `main.py`, `sean.py`
- Added FiFi to `CHANNELS_CONFIG` in `config.py` (tracking-only mode, min_trade_contracts=0)
- Added configurable `message_history_limit` per channel in CHANNELS_CONFIG and `main.py`
- Implemented all 5 approved enhancements from research:
  1. Position ledger injection (open positions as compact JSON in prompt)
  2. Reply context with PRIMARY/REPLYING TO tags
  3. Last 10 messages with time deltas
  4. Negative constraint firewall (Do NOT rules)
  5. Role ping signal (has_alert_ping flag)
- Implemented custom `_normalize_entry()` with stop-out detection, embedded contract regex, size normalization, 0DTE default
- Implemented `build_prompt()` with few-shot examples covering buy, trim, exit, and null categories
- Added multi-trade detection instructions and few-shot examples for mixed trims and multi-ticker buys
- Added "sold all" to exit clarification in prompt

#### Backtest Results
- **v1 prompt**: 961 messages tested, 92.7% accuracy, 28 false positives (20 watchlist, 4 corrections, 3 intent, 1 misclassification)
- **v2 prompt (optimized)**: Eliminated all 28 false positives, 297 total actionable signals matching research estimate of 298, 0 errors

#### Decisions
- Used Option A (clean infrastructure pass-through) for position ledger injection rather than config dict hack
- Per-channel message history limit via CHANNELS_CONFIG rather than global increase
- Time delta formatting in `build_prompt()` rather than modifying shared `get_channel_message_history()`

## Next Steps
- Deploy to production in tracking-only mode and monitor parse accuracy on live messages
- Evaluate accuracy over 1-2 weeks of live tracking before enabling trade execution
- Consider increasing min_trade_contracts above 0 after validation period
