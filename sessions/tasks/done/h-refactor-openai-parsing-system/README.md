---
name: h-refactor-openai-parsing-system
branch: feature/openai-parsing-overhaul
status: complete
created: 2026-01-27
completed: 2026-01-27
---

# Overhaul OpenAI Parsing System

## Problem/Goal
The current OpenAI parsing system has latency bottlenecks and accuracy issues. The goal is to completely overhaul the parsing system to:
1. **Reduce latency** as much as possible
2. **Increase accuracy** of alert parsing
3. Support 4 standardized alert types: BUY, TRIM, EXIT, COMMENTARY
4. Return validated, standardized JSON for all actionable alerts
5. Handle replies, forwards, and contextual message history (last 5 messages)

## Success Criteria
- [x] Pydantic schemas defined for BUY, TRIM, EXIT, COMMENTARY alerts
- [x] OpenAI JSON mode enabled for guaranteed valid JSON output
- [x] Few-shot examples added to prompts (2-3 per alert type)
- [x] LLM directly parses dates to YYYY-MM-DD format (remove Python date parsing)
- [x] Last 5 messages sent as context for parsing
- [x] Reply and forward messages properly handled with context
- [x] Parsing latency reduced by measurable amount
- [x] All actionable alerts validated against Pydantic schemas
- [x] Bot runs successfully with new parsing system
- [x] Message edits logged but do not trigger duplicate trades

## Subtasks
- [x] `phase-1-schemas-and-validation.md` - Pydantic schemas, JSON mode, few-shot examples
- [x] `phase-2-context-handling.md` - Message history, replies, forwards, active positions
- [x] `phase-3-latency-optimization.md` - Streaming API, model tuning, caching

## Context Manifest
<!-- Archived - task complete. See Work Log for implementation details. -->

### Summary of Implementation

The OpenAI parsing system was overhauled to improve accuracy and reduce latency:

1. **Pydantic Schemas**: BuyAlert, TrimAlert, ExitAlert, CommentaryAlert models enforce JSON structure
2. **JSON Mode**: OpenAI `response_format={"type": "json_object"}` guarantees valid JSON
3. **LLM Date Parsing**: Dates now parsed directly to YYYY-MM-DD by the LLM (removed Python date parsing)
4. **Few-Shot Examples**: 12 examples in SeanParser prompt (3 per alert type)
5. **Message History**: Last 5 messages fetched via `channel.history()` and included in prompt
6. **Caching**: 5-minute TTL response cache with normalized message keys
7. **Fallback Model**: gpt-4o-mini primary, gpt-4o fallback with exponential backoff

### Key Files Modified
- `channels/base_parser.py` - Core parsing logic with schemas, caching, retry
- `channels/sean.py` - Prompt with few-shot examples and context handling
- `main.py` - Message history fetcher, forward detection
- `trade_executor.py` - Message history threading

### Expected Alert Schema Fields
- `action`: "buy" | "trim" | "exit" | "null"
- `ticker`: Uppercase string, no $ prefix
- `strike`: Float
- `type`: "call" | "put"
- `expiration`: YYYY-MM-DD format
- `price`: Float or "BE" for breakeven
- `size`: "full" | "half" | "lotto"

## Work Log

### 2026-01-27

#### Completed

**Phase 1: Schemas, JSON Mode, Few-Shot Examples**
- Added Pydantic schemas (BuyAlert, TrimAlert, ExitAlert, CommentaryAlert) to `channels/base_parser.py`
- Enabled OpenAI JSON mode with `response_format={"type": "json_object"}`
- Updated SeanParser DATE RULES to output YYYY-MM-DD directly
- Added 12 few-shot examples to SeanParser prompt (3 per alert type)
- Added Pydantic validation after JSON parsing

**Phase 2: Context Handling**
- Added `get_channel_message_history()` method to `main.py`
- Updated `on_message` and `on_message_edit` to fetch and pass message history
- Updated `process_trade` and `_blocking_handle_trade` in `trade_executor.py` to accept message_history
- Updated BaseParser to accept `message_history` parameter
- Added RECENT CONVERSATION HISTORY section to SeanParser prompt
- Added forward message detection in `_extract_message_content()`

**Phase 3: Latency Optimization**
- Added response caching with normalized message keys (5-min TTL)
- Implemented fallback model strategy (gpt-4o-mini -> gpt-4o)
- Added retry logic with exponential backoff
- Added latency and token tracking

**Bug Fixes**
- Modified `on_message_edit` to LOG ONLY (no trade execution) to prevent duplicate orders from edited messages
- Fixed cache key to include message history context

#### Decisions
- Used gpt-4o-mini as primary model with gpt-4o fallback for better latency
- 5-minute cache TTL balances freshness with performance
- Message edits are logged but not executed to prevent accidental duplicate trades

#### Files Modified
- `channels/base_parser.py` - Pydantic schemas, JSON mode, caching, retry logic
- `channels/sean.py` - Few-shot examples, YYYY-MM-DD date rules, context history section
- `main.py` - Message history fetcher, forward detection, edit handler change
- `trade_executor.py` - Message history parameter threading
