---
name: h-refactor-openai-parsing-system
branch: feature/openai-parsing-overhaul
status: pending
created: 2026-01-27
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
- [ ] Pydantic schemas defined for BUY, TRIM, EXIT, COMMENTARY alerts
- [ ] OpenAI JSON mode enabled for guaranteed valid JSON output
- [ ] Few-shot examples added to prompts (2-3 per alert type)
- [ ] LLM directly parses dates to YYYY-MM-DD format (remove Python date parsing)
- [ ] Last 5 messages sent as context for parsing
- [ ] Reply and forward messages properly handled with context
- [ ] Parsing latency reduced by measurable amount
- [ ] All actionable alerts validated against Pydantic schemas
- [ ] Bot runs successfully with new parsing system

## Subtasks
- [ ] `phase-1-schemas-and-validation.md` - Pydantic schemas, JSON mode, few-shot examples
- [ ] `phase-2-context-handling.md` - Message history, replies, forwards, active positions
- [ ] `phase-3-latency-optimization.md` - Streaming API, model tuning, caching

## Context Manifest
<!-- Added by context-gathering agent -->

### How the Current OpenAI Parsing System Works

#### Overview of the Message Processing Flow

When a Discord message arrives from a monitored trading channel, it flows through a well-defined pipeline that involves Discord event handling, message content extraction, OpenAI API calls for natural language parsing, JSON response handling, and finally trade execution. Understanding this flow is critical because the refactoring touches every step.

#### Step 1: Discord Message Reception (main.py)

The `EnhancedDiscordClient` class (located at `/Users/mautasimhussain/trading-bots/RHTBv5/main.py`) receives messages through the `on_message` event handler starting at line 399. When a message arrives:

1. **Command Filtering**: If the message is from the command channel and starts with `!`, it routes to command handling (line 403-405)
2. **Channel Handler Lookup**: The `ChannelHandlerManager` (defined at lines 160-186) checks if the channel_id has a registered parser via `get_handler(message.channel.id)`
3. **Content Extraction**: The `_extract_message_content` method (lines 454-492) extracts text from both regular messages and embeds

The content extraction is particularly important because it handles **replies**. Here is the exact code pattern for reply handling (lines 469-483):

```python
# Handle replies
if message.reference and isinstance(message.reference.resolved, discord.Message):
    original_msg = message.reference.resolved
    original_embed_title = ""
    original_embed_desc = ""

    if original_msg.embeds:
        orig_embed = original_msg.embeds[0]
        original_embed_title = orig_embed.title or ""
        original_embed_desc = orig_embed.description or ""

    original_content = original_msg.content or ""
    original_full_text = f"Title: {original_embed_title}\nDesc: {original_embed_desc}" if original_embed_title else original_content

    message_meta = (current_full_text, original_full_text)  # <-- Tuple format for replies
    raw_msg = f"Reply: '{current_full_text}'\nOriginal: '{original_full_text}'"
else:
    message_meta = (current_embed_title, current_embed_desc) if current_embed_title else current_content
    raw_msg = current_full_text
```

**Key Insight**: For replies, `message_meta` is a **tuple** of `(current_message, original_message)`. For standard messages, it can be either a tuple `(title, description)` for embeds or a plain string for regular content. This polymorphic handling must be preserved.

**Missing Feature**: There is NO "last 5 messages" context fetching currently implemented. Discord.py provides `channel.history(limit=5)` but this is not being called anywhere.

#### Step 2: Parser Selection and Prompt Building (channels/base_parser.py, channels/sean.py)

The `BaseParser` class at `/Users/mautasimhussain/trading-bots/RHTBv5/channels/base_parser.py` defines the abstract interface. Each channel has a concrete parser implementation. Currently only `SeanParser` exists at `/Users/mautasimhussain/trading-bots/RHTBv5/channels/sean.py`.

The `parse_message` method in BaseParser (lines 132-198) orchestrates:
1. Stores message metadata in `self._current_message_meta`
2. Calls the subclass's `build_prompt()` method
3. Calls `_call_openai()` to make the API request
4. Normalizes and standardizes the results

**SeanParser's build_prompt() Method** (sean.py lines 9-101):

This is the core prompt that needs modification. Currently:

```python
def build_prompt(self) -> str:
    # --- Dynamically get the current date ---
    today = datetime.now(timezone.utc)
    current_year = today.year
    today_str = today.strftime('%Y-%m-%d')

    # --- Handle standard messages and replies ---
    primary_message = ""
    context_message = ""
    if isinstance(self._current_message_meta, tuple):
        # It's a reply: (current_message, original_message)
        primary_message = self._current_message_meta[0]
        context_message = self._current_message_meta[1]
    else:
        # It's a standard message
        primary_message = self._current_message_meta
```

The prompt then includes several sections:
- **MESSAGE CONTEXT** (lines 31-35): Explains PRIMARY vs ORIGINAL message
- **ACTION DEFINITIONS** (lines 37-41): buy, trim, exit, null
- **DATE RULES** (lines 43-48): Currently instructs LLM NOT to parse dates
- **OUTPUT FORMAT RULES** (lines 50-57): Field specifications
- **SIZE RULES** (lines 59-63): half, lotto, full
- **WEEKLY TRADE PLAN FILTERING** (lines 66-71): Filters out planning messages
- **EXTRACTION LOGIC & RULES** (lines 73-93): Various edge cases

**Critical Date Handling Issue** (sean.py lines 43-48):
```python
--- DATE RULES ---
1.  Today's date is {today_str}.
2.  For expiration dates, extract and return exactly what is mentioned in the message.
3.  If the message mentions "0dte", return "0dte" as the expiration value.
4.  Examples: "1/16" -> "1/16", "Sep 19" -> "Sep 19", "0dte" -> "0dte"
5.  Do NOT interpret or convert dates - just extract the raw expiration text from the message.
```

But then in BaseParser, there is **extensive Python date parsing** (lines 200-301) via `_smart_year_detection()` that tries to convert these raw strings to YYYY-MM-DD. This is the inefficiency: the LLM is told NOT to parse dates, then Python code has to do it anyway with complex regex patterns.

#### Step 3: OpenAI API Call (base_parser.py)

The `_call_openai` method (lines 75-130) makes the actual API request:

```python
def _call_openai(self, prompt: str, logger) -> Tuple[Optional[Union[Dict, List]], float]:
    """Makes the API call to OpenAI and parses the JSON response."""
    start_time = datetime.now(timezone.utc)
    try:
        params = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}]
        }
        if self.model != "gpt-5-mini":
            params["temperature"] = 0

        response = self.client.chat.completions.create(**params)
        # ... latency logging ...
        content = response.choices[0].message.content.strip()

        # Handle markdown code blocks
        if content.startswith("```json"):
            content = content[7:]  # Remove ```json
            if content.endswith("```"):
                content = content[:-3]  # Remove closing ```
        # ... more markdown handling ...

        parsed_json = json.loads(content)
        return parsed_json, latency
```

**Missing Features**:
1. **No `response_format` parameter**: The code does NOT use `response_format={"type": "json_object"}` which would guarantee valid JSON
2. **Manual markdown stripping**: Lines 94-102 manually handle ```json``` blocks because JSON mode isn't enabled
3. **No few-shot examples**: The prompt is instruction-only with no example input/output pairs
4. **No Pydantic validation**: JSON is parsed but not validated against any schema

#### Step 4: Post-Processing and Date Parsing (base_parser.py)

After the OpenAI response is received, `parse_message` (lines 150-198) processes results:

1. **Action Standardization** (lines 157-168): Uses `_standardize_action()` to map variations like "entry" -> "buy", "scale" -> "trim", etc.
2. **Null Filtering** (lines 172-174): Skips non-actionable alerts
3. **Metadata Addition** (lines 177-178): Adds channel_id and received_ts
4. **Normalization Hook** (line 182): Calls `_normalize_entry()` which triggers date parsing

The `_normalize_entry` method (lines 371-392) applies date parsing:
```python
def _normalize_entry(self, entry: dict) -> dict:
    if 'expiration' in entry and entry['expiration']:
        original_exp = entry['expiration']

        # First try monthly expiration parsing (e.g., "JAN 2026")
        parsed_exp = self._parse_monthly_expiration(original_exp, print)

        # If not a monthly expiration, try regular date parsing
        if parsed_exp == original_exp:
            parsed_exp = self._smart_year_detection(original_exp, print)

        if parsed_exp != original_exp:
            entry['expiration'] = parsed_exp
    return entry
```

**The Date Parsing Code That Should Be Removed**:

`_smart_year_detection` (lines 200-301) handles:
- Already YYYY-MM-DD format (returns as-is)
- 0DTE/today cases
- Date patterns: MM/DD/YYYY, MM-DD-YYYY, YYYY-MM-DD, MM-DD, MM/DD
- Month name formats: "January 16 2026", "Jan 16"
- Smart year detection (if date passed this year, assume next year)

`_parse_monthly_expiration` (lines 303-369) handles:
- Monthly expiration formats like "JAN 2026"
- Calculates third Friday of the month

**These 170+ lines of Python date parsing should be replaced by LLM-native date parsing to YYYY-MM-DD directly.**

#### Step 5: Trade Execution Integration (trade_executor.py)

The `TradeExecutor` class at `/Users/mautasimhussain/trading-bots/RHTBv5/trade_executor.py` receives parsed results via `process_trade` (lines 234-593).

Key integration points relevant to parsing:

1. **Action Handling** (lines 300-308):
```python
action_value = trade_obj.get("action")
action = action_value.lower() if action_value else ""

if not action or action == "null":
    log_func(f"Skipping null action from {handler.name}")
    continue
```

2. **Contract Detail Resolution** (lines 357-361):
```python
symbol = trade_obj.get("ticker") or (active_position.get("trader_symbol") or active_position.get("symbol") if active_position else None)
strike = trade_obj.get("strike") or (active_position.get("strike") if active_position else None)
expiration = trade_obj.get("expiration") or (active_position.get("expiration") if active_position else None)
opt_type = trade_obj.get("type") or (active_position.get("type") if active_position else None)
```

The trade executor expects these exact fields from the parser. Any schema changes must maintain compatibility.

3. **Feedback Logger** (lines 22-159): The `ChannelAwareFeedbackLogger` logs parsed results to CSV for debugging and provides fallback lookups for incomplete parses.

### What Needs to Change for the Refactoring

#### For Phase 1: Schemas, JSON Mode, Few-Shot Examples

**File: `/Users/mautasimhussain/trading-bots/RHTBv5/channels/base_parser.py`**

1. **Add Pydantic Import and Schemas** (new code at top, after line 7):
   - Create `BuyAlert`, `TrimAlert`, `ExitAlert`, `CommentaryAlert` Pydantic models
   - These must match the field names currently expected: ticker, strike, type, expiration, price, size, action

2. **Enable JSON Mode** (modify `_call_openai` at line 79-86):
   Change:
   ```python
   params = {
       "model": self.model,
       "messages": [{"role": "user", "content": prompt}]
   }
   ```
   To:
   ```python
   params = {
       "model": self.model,
       "messages": [{"role": "user", "content": prompt}],
       "response_format": {"type": "json_object"}
   }
   ```

3. **Remove Markdown Handling** (delete lines 94-102): With JSON mode, no markdown will be returned

4. **Add Pydantic Validation** (after line 109): Validate parsed JSON against appropriate schema based on action field

5. **Remove or Deprecate Date Parsing** (lines 200-369): Keep for backward compatibility but make it a no-op if date is already YYYY-MM-DD

**File: `/Users/mautasimhussain/trading-bots/RHTBv5/channels/sean.py`**

1. **Update DATE RULES** (lines 43-48): Change to instruct LLM to output YYYY-MM-DD directly

2. **Add Few-Shot Examples** (new section after line 93): Add 2-3 examples per alert type showing input message and expected JSON output

**File: `/Users/mautasimhussain/trading-bots/RHTBv5/requirements.txt`**

Add: `pydantic` (note: pydantic 2.12.5 is already installed as a dependency of openai, but should be explicit)

#### For Phase 2: Context Handling

**File: `/Users/mautasimhussain/trading-bots/RHTBv5/main.py`**

1. **Add Message History Fetcher** (new method in EnhancedDiscordClient):
   ```python
   async def get_channel_message_history(self, channel, limit=5):
       messages = []
       async for msg in channel.history(limit=limit):
           messages.append(msg)
       return messages[::-1]  # Reverse to chronological order
   ```

2. **Pass History to Parser** (modify `on_message` around line 420): Fetch history and include in message_meta

**File: `/Users/mautasimhussain/trading-bots/RHTBv5/channels/sean.py`**

1. **Update Prompt to Include History**: Add `RECENT CONVERSATION HISTORY` section

2. **Handle Forward Detection**: Add parsing logic for Discord forward format

**File: `/Users/mautasimhussain/trading-bots/RHTBv5/trade_executor.py`**

1. **Inject Active Positions**: For trim/exit, include current position info in prompt context

#### For Phase 3: Latency Optimization

**File: `/Users/mautasimhussain/trading-bots/RHTBv5/channels/base_parser.py`**

1. **Consider Streaming API**: Use `stream=True` for faster first-byte response
2. **Token Optimization**: Reduce prompt verbosity where possible
3. **Model Selection**: Consider gpt-4o-mini for simpler alerts

### Technical Reference Details

#### Current Configuration (config.py)

```python
# Channel Config relevant to parsing
CHANNELS_CONFIG = {
    "Sean": {
        "live_id": 1072555808832888945,
        "test_id": 1398211580470235176,
        "parser": "SeanParser",
        "model": "gpt-4o-2024-08-06",  # Model for OpenAI API
        # ... other config
    }
}
```

#### Expected Field Names (must be maintained)

From `trade_executor.py` expectations:
- `action`: "buy" | "trim" | "exit" | "null"
- `ticker`: String, uppercase, no $ prefix
- `strike`: Float/Number
- `type`: "call" | "put"
- `expiration`: String in YYYY-MM-DD format (after parsing)
- `price`: Float/Number or "BE" for breakeven
- `size`: "full" | "half" | "lotto"

#### Pydantic Schema Recommendations

```python
from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional, Union
from datetime import date

class BuyAlert(BaseModel):
    action: Literal["buy"]
    ticker: str
    strike: float
    type: Literal["call", "put"] = Field(alias="option_type")
    expiration: date  # YYYY-MM-DD format
    price: float
    size: Literal["full", "half", "lotto"] = "full"

    @field_validator('ticker')
    @classmethod
    def normalize_ticker(cls, v):
        return v.upper().replace('$', '')

class TrimAlert(BaseModel):
    action: Literal["trim"]
    ticker: str
    strike: Optional[float] = None
    type: Optional[Literal["call", "put"]] = None
    expiration: Optional[date] = None
    price: Union[float, Literal["BE"]]

class ExitAlert(BaseModel):
    action: Literal["exit"]
    ticker: str
    strike: Optional[float] = None
    type: Optional[Literal["call", "put"]] = None
    expiration: Optional[date] = None
    price: Union[float, Literal["BE"]]

class CommentaryAlert(BaseModel):
    action: Literal["null"]
    message: Optional[str] = None
```

#### File Locations Summary

| Purpose | File Path | Key Lines |
|---------|-----------|-----------|
| Discord event handling | `/Users/mautasimhussain/trading-bots/RHTBv5/main.py` | 399-428 (on_message), 454-492 (_extract_message_content) |
| Abstract parser interface | `/Users/mautasimhussain/trading-bots/RHTBv5/channels/base_parser.py` | 9-430 |
| OpenAI API call | `/Users/mautasimhussain/trading-bots/RHTBv5/channels/base_parser.py` | 75-130 (_call_openai) |
| Date parsing (to remove) | `/Users/mautasimhussain/trading-bots/RHTBv5/channels/base_parser.py` | 200-369 |
| Sean prompt | `/Users/mautasimhussain/trading-bots/RHTBv5/channels/sean.py` | 9-101 (build_prompt) |
| Trade executor integration | `/Users/mautasimhussain/trading-bots/RHTBv5/trade_executor.py` | 234-593 (process_trade) |
| Channel configuration | `/Users/mautasimhussain/trading-bots/RHTBv5/config.py` | 85-103 (CHANNELS_CONFIG) |
| Dependencies | `/Users/mautasimhussain/trading-bots/RHTBv5/requirements.txt` | All |

#### Discord.py API for Message History

The discord.py library provides `channel.history()` for fetching message history:

```python
# From discord/abc.py (installed package)
async def history(
    self,
    *,
    limit: Optional[int] = 100,
    before: Optional[SnowflakeTime] = None,
    after: Optional[SnowflakeTime] = None,
    around: Optional[SnowflakeTime] = None,
    oldest_first: Optional[bool] = None,
) -> AsyncIterator[Message]:
```

Usage pattern:
```python
messages = []
async for msg in channel.history(limit=5):
    messages.append(msg)
# Note: Returns newest first by default
```

#### OpenAI JSON Mode Requirements

To use JSON mode, the model must be one of the following:
- gpt-4o-2024-08-06 (currently configured)
- gpt-4o-mini-2024-07-18
- gpt-4-turbo
- gpt-3.5-turbo-0125

The prompt MUST mention "JSON" somewhere for JSON mode to work. The current prompts do this implicitly in the output instructions.

## Technical Analysis (from Gemini)

### Current System Weaknesses

1. **Latency Bottlenecks:**
   - OpenAI API calls dominate processing time
   - Each message parsed synchronously within thread
   - Post-processing (markdown stripping, JSON parsing) adds overhead

2. **Accuracy Issues:**
   - **Date Parsing Conflict**: LLM instructed NOT to parse dates, but Python code tries to parse them anyway - this is inefficient and error-prone
   - **No Few-Shot Examples**: Prompts are instruction-only, reducing accuracy
   - **Limited Context**: Only immediate replies supported, no message history
   - **No Schema Validation**: JSON structure is implicit, not programmatically enforced
   - **Subjectivity in Filtering**: Rules for "size" and filtering rely on LLM interpretation

3. **Context Handling Gaps:**
   - Only immediate replies are supported
   - "Last 5 messages" not implemented
   - No specific forward handling

### Recommended Architecture

#### Standardized JSON Schemas (Pydantic)

```python
from pydantic import BaseModel, Field, confloat, constr
from typing import Literal, Optional, Union
from datetime import date

class BaseTradeAlert(BaseModel):
    channel_id: int
    channel_name: str
    received_ts: str
    action: Literal["buy", "trim", "exit", "commentary"]
    ticker: Optional[constr(min_length=1, max_length=10, to_upper=True)] = None

class BuyAlert(BaseTradeAlert):
    action: Literal["buy"] = "buy"
    ticker: constr(min_length=1, max_length=10, to_upper=True)
    strike: confloat(gt=0)
    option_type: Literal["call", "put"] = Field(alias="type")
    expiration: date  # LLM provides YYYY-MM-DD directly
    price: confloat(gt=0)
    size: Literal["full", "half", "lotto"] = "full"

class TrimAlert(BaseTradeAlert):
    action: Literal["trim"] = "trim"
    ticker: constr(min_length=1, max_length=10, to_upper=True)
    strike: Optional[confloat(gt=0)] = None
    option_type: Optional[Literal["call", "put"]] = Field(None, alias="type")
    expiration: Optional[date] = None
    price: Union[confloat(gt=0), Literal['BE']]
    is_breakeven: bool = False

class ExitAlert(BaseTradeAlert):
    action: Literal["exit"] = "exit"
    ticker: constr(min_length=1, max_length=10, to_upper=True)
    strike: Optional[confloat(gt=0)] = None
    option_type: Optional[Literal["call", "put"]] = Field(None, alias="type")
    expiration: Optional[date] = None
    price: Union[confloat(gt=0), Literal['BE']]
    is_breakeven: bool = False

class CommentaryAlert(BaseTradeAlert):
    action: Literal["commentary"] = "commentary"
    message: str
```

#### Context Handling Architecture

1. **Message History Fetcher**: `get_channel_message_history(channel_id, limit=5)`
2. **Prompt Sections**:
   - `PRIMARY MESSAGE`: Current message being parsed
   - `ORIGINAL MESSAGE`: If reply, the parent message
   - `RECENT CONVERSATION HISTORY`: Last 5 messages chronologically
   - `ACTIVE POSITIONS`: For trim/exit, inject current positions
3. **Forward Detection**: Parse Discord's forward representation separately

### Implementation Phases

**Phase 1: Accuracy & Output Reliability**
- Define Pydantic schemas
- Enable OpenAI JSON mode (`response_format={"type": "json_object"}`)
- Add few-shot examples to prompts (2-3 per alert type)
- Instruct LLM to parse dates directly to YYYY-MM-DD
- Implement Pydantic validation in BaseParser
- Remove Python date parsing code

**Phase 2: Context Handling**
- Implement message history fetcher with caching
- Add "Last 5 Messages" to prompt
- Inject active positions for trim/exit context
- Handle forwarded messages

**Phase 3: Latency Optimization**
- Implement OpenAI streaming API (optional)
- Monitor and tune prompt token usage
- Consider faster models for simpler alerts
- Add retry/backoff logic

### Key Files to Modify

| File | Changes |
|------|---------|
| `channels/base_parser.py` | Add JSON mode, Pydantic validation, remove date parsing |
| `channels/sean.py` | Add few-shot examples, update prompt structure |
| `main.py` | Add message history fetcher, forward detection |
| `trade_executor.py` | Inject active positions context |
| `requirements.txt` | Add pydantic |

### Additional Ideas

1. **Confidence Scoring**: LLM returns confidence score for manual review
2. **Structured Error Feedback**: Send validation failures to debug channel
3. **Dynamic Prompt Templates**: Store prompts externally (YAML) for easy iteration
4. **Multi-Model Strategy**: Use gpt-3.5-turbo for simple alerts, gpt-4o for complex
5. **"What-if" Parsing Mode**: `!parse <message>` command to test parsing

## User Notes
- Goal is to reduce latency AND increase accuracy
- Four alert types: BUY, TRIM, EXIT, COMMENTARY
- Must handle replies, forwards, and last 5 messages as context
- Standardized JSON output for all actionable alerts

## Work Log
<!-- Updated as work progresses -->
- [2026-01-27] Task created with comprehensive technical analysis from Gemini
