---
name: m-standardize-parser-json-schema
branch: feature/standardize-parser-schema
status: completed
created: 2026-02-12
---

# Standardize Parser JSON Output Schema

## Problem/Goal
All parsers (SeanParser, FiFiParser, IanParser, RyanParser) should output a consistent, standardized JSON schema. Currently there are inconsistencies:
- `price: "market"` not allowed in Trim/Exit schemas
- Redundant normalization across parsers and executor
- **"weekly" expiration parsed incorrectly** - should be next Friday, not 0DTE (Feb 9th AAPL bug: $0.25 vs $1.90)
- **Sizing not normalized** - needs 3 values: "full", "half", "small"
- **Stop updates not needed** - ignore, return as null (BE set automatically after trim)
- **Entry sizing inconsistent** - Sean 10%, others 5%, min 1 contract
- **Trim sizing hardcoded** - first trim should be 50%, subsequent 25%
- **Ryan multiplier wrong** - currently 1.0, should be 0.5

## Success Criteria
- [x] TrimAlert/ExitAlert allow `price: "market"`
- [x] Field validators: ticker uppercase, type call/put normalization
- [x] `get_weekly_expiry_date()` helper in BaseParser
- [x] "weekly" → next Friday in all parser prompts
- [x] Sizing normalized: full (default), half, small
- [x] Stop updates → return "null" (ignore)
- [x] Ryan multiplier: 0.5 (5% portfolio)
- [x] config.py: INITIAL_TRIM_PCT=0.50, SUBSEQUENT_TRIM_PCT=0.25
- [x] Trim count tracking via PerformanceTracker
- [x] All files compile (no formal test suite exists)

## Context Manifest
<!-- Added by context-gathering agent -->

### Key Files
- `channels/base_parser.py` - Pydantic schemas, validation, base class
- `channels/sean.py` - Sean parser (LLM-based)
- `channels/fifi.py` - FiFi parser (LLM-based)
- `channels/ian.py` - Ian parser (LLM-based, has `stop_update`)
- `channels/ryan.py` - Ryan parser (regex-based, outputs `price: "market"`)
- `trade_executor.py` - Consumes parsed output

### Current Schemas (base_parser.py)
```python
BuyAlert:   action, ticker, strike, type, expiration, price, size
TrimAlert:  action, ticker, price, [strike, type, expiration optional]
ExitAlert:  action, ticker, price, [strike, type, expiration optional]
CommentaryAlert: action="null"
```

### Required Schema Changes

1. **TrimAlert / ExitAlert** - Add `"market"` to price union:
   ```python
   price: Union[float, Literal["BE", "market"]]
   ```

2. **BuyAlert** - Normalize size field:
   ```python
   size: Literal["full", "half", "small"] = "full"
   ```

3. **Field validators** on all schemas:
   - `ticker`: uppercase, strip `$`
   - `type`: normalize c/call/calls -> "call", p/put/puts -> "put"

4. **Stop updates** - Ignore, return as "null":
   - Do NOT add StopUpdateAlert schema
   - Any stop_update action → return CommentaryAlert (null)
   - BE stop is set automatically after first trim

### Expiration Parsing Fix

Add `get_weekly_expiry_date()` helper to BaseParser:
```python
def get_weekly_expiry_date(self) -> str:
    """Returns next Friday's date for 'weekly' keyword"""
    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # 0=Mon, 4=Fri
    if weekday >= 4:  # Fri/Sat/Sun → Next Friday
        days_ahead = 7 - weekday + 4
    else:  # Mon-Thu → This Friday
        days_ahead = 4 - weekday
    target_date = now + timedelta(days=days_ahead)
    return target_date.strftime('%Y-%m-%d')
```

Update prompts:
- "0dte"/"today" → today's date
- "weekly" → `{weekly_exp}` (calculated next Friday, NOT 0DTE)
- "next week" → Friday after next

### Sizing Normalization

Map all sizing keywords to 3 values:
| Output | Keywords |
|--------|----------|
| "full" | default, "full size" |
| "half" | "half", "1/2", "starter", "small size" |
| "small" | "lotto", "1/8", "1/4", "tiny", "lite", "super small" |

### Entry Sizing (config.py)

| Channel | Multiplier | Portfolio % |
|---------|------------|-------------|
| Sean | 1.0 | 10% |
| FiFi | 0.5 | 5% |
| Ian | 0.5 | 5% |
| Ryan | 0.5 | 5% ← **fix from 1.0** |

- Min: 1 contract
- Max: 2 contracts (user will adjust after testing)

### Trim Sizing (trade_executor.py)

Add to config.py:
```python
INITIAL_TRIM_PCT = 0.50      # First trim = 50%
SUBSEQUENT_TRIM_PCT = 0.25   # Subsequent trims = 25%
```

Logic in `_execute_sell_order`:
```python
trim_count = count_previous_trims(trade_id)  # via PerformanceTracker
if trim_count == 0:
    trim_pct = INITIAL_TRIM_PCT   # 50%
else:
    trim_pct = SUBSEQUENT_TRIM_PCT # 25%
sell_quantity = max(1, int(total_quantity * trim_pct))
```

### Parser-Specific Cleanup

**IanParser (`channels/ian.py`)**:
- Stop updates → return "null" (ignore)
- Remove any stop_update handling code

**RyanParser (`channels/ryan.py`)**:
- Update multiplier in config: 1.0 → 0.5 (5% portfolio)
- `price: "market"` will now pass validation

**FiFiParser (`channels/fifi.py`)**:
- Fix "weekly" → next Friday (use `get_weekly_expiry_date()`)
- Update sizing normalization: full/half/small only
- Stop updates → return null
- Ensure `"market"` mentioned for exits without price

**SeanParser (`channels/sean.py`)**:
- Fix "weekly" → next Friday (use `get_weekly_expiry_date()`)
- Update sizing normalization: full/half/small only

## User Notes
- Analysis done with Gemini on 2026-02-12
- Stop updates ignored entirely (return as null) - BE set automatically after first trim
- User will adjust max contracts (currently 2) after testing phase

## Work Log

### 2026-02-12

#### Completed
- Fixed weekly expiration parsing: "weekly" now resolves to next Friday instead of 0DTE
- Normalized sizing to 3 values: full, half, small (removed lotto)
- Stop updates return null (ignored) -- BE set automatically after first trim
- Added trim percentages: INITIAL_TRIM_PCT=0.50, SUBSEQUENT_TRIM_PCT=0.25
- Fixed Ryan multiplier: 1.0 -> 0.5 (5% portfolio)
- Added `get_trim_count()` to PerformanceTracker for trim count tracking
- Updated Pydantic schemas to allow `price: "market"` in TrimAlert/ExitAlert

#### Files Modified
- `channels/base_parser.py` -- Pydantic schema updates, field validators
- `channels/sean.py` -- Weekly expiration fix, sizing normalization
- `channels/fifi.py` -- Weekly expiration fix, sizing normalization, stop->null
- `channels/ian.py` -- Stop updates return null
- `config.py` -- INITIAL_TRIM_PCT, SUBSEQUENT_TRIM_PCT, Ryan multiplier
- `trade_executor.py` -- Trim percentage logic using trim count
- `performance_tracker.py` -- get_trim_count() method

#### Notes
- Task originated from Feb 9th AAPL bug: $0.25 vs $1.90 due to 0DTE instead of weekly
- All files compile successfully (no formal test suite)
