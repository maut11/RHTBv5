# Additional Guidance

@sessions/CLAUDE.sessions.md

This file provides instructions for Claude Code for working in the cc-sessions framework.

## OpenAI Parsing System Architecture

The trading bot uses OpenAI's API to parse Discord trading alerts into structured JSON for execution.

### Alert Types and Schemas

Four Pydantic schemas define valid alert structures (see `channels/base_parser.py` lines 100-195):

- **BuyAlert**: New position entries - requires ticker, strike, type, expiration, price, size
- **TrimAlert**: Partial exits - requires ticker, price; other fields optional (resolved from active positions)
- **ExitAlert**: Full position closes - requires ticker, price; other fields optional
- **CommentaryAlert**: Non-actionable messages - action="null"

### Model Strategy and Reliability

The system uses a tiered approach for reliability and speed:

1. **Primary model**: gpt-4o-mini (faster, cheaper)
2. **Fallback model**: gpt-4o (more accurate for complex messages)
3. **JSON mode**: Always enabled via `response_format: {"type": "json_object"}`
4. **Retry logic**: Exponential backoff (1s, 2s, 4s) for transient errors

Implementation: `channels/base_parser.py` lines 291-399

### Response Caching

Duplicate messages are cached to avoid redundant API calls:
- TTL: 5 minutes
- Key: Normalized message content + message history context
- Location: `channels/base_parser.py` `ParseCache` class (lines 15-96)

### Message Context Handling

When parsing a message, the system provides context to improve accuracy:

1. **Message history**: Last 5 messages from the channel (see `main.py` lines 559-602)
2. **Reply context**: Original message included when parsing a reply
3. **Forward detection**: Forwarded messages are detected and parsed appropriately (see `main.py` lines 507-532)

### Date Parsing

The LLM directly converts dates to YYYY-MM-DD format. Prompt instructions in `channels/sean.py` lines 43-57 specify:
- 0DTE becomes today's date
- Dates without year use smart year detection (future = current year, passed = next year)
- Monthly expirations (e.g., "JAN 2026") resolve to third Friday

Fallback Python parsing exists in `base_parser.py` lines 521-690 for edge cases.

### Message Edits

When a message is edited:
- Edit is logged with original and edited content
- **No trade action is taken** to prevent duplicate executions
- Notification sent to commands webhook

Implementation: `main.py` lines 436-491
