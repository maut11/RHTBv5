---
name: m-standardize-parser-json-schema
branch: feature/standardize-parser-schema
status: pending
created: 2026-02-12
---

# Standardize Parser JSON Output Schema

## Problem/Goal
All parsers (SeanParser, FiFiParser, IanParser, RyanParser) should output a consistent, standardized JSON schema. Currently there are inconsistencies:
- `stop_update` action from Ian not in schemas
- `new_stop` field not defined
- `price: "market"` not allowed in Trim/Exit schemas
- Redundant normalization across parsers and executor

## Success Criteria
- [ ] All parsers output validated Pydantic models
- [ ] Schemas updated: `BuyAlert`, `TrimAlert`, `ExitAlert` + new `StopUpdateAlert`
- [ ] Field validators handle normalization (ticker uppercase, type call/put, price types)
- [ ] `_standardize_action()` handles `stop_update` keywords
- [ ] Individual parser `_normalize_entry()` methods cleaned up
- [ ] All existing tests pass
- [ ] New validation tests added

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

2. **NEW StopUpdateAlert**:
   ```python
   class StopUpdateAlert(BaseModel):
       action: Literal["stop_update"]
       ticker: str
       strike: Optional[float] = None
       type: Optional[Literal["call", "put"]] = None
       expiration: Optional[str] = None
       new_stop: Union[float, Literal["BE", "LOD", "OP"]]
   ```

3. **Field validators** on all schemas:
   - `ticker`: uppercase, strip `$`
   - `type`: normalize c/call/calls -> "call", p/put/puts -> "put"
   - `new_stop`: normalize b/e/breakeven -> "BE"

4. **Update ALERT_SCHEMAS dict**:
   ```python
   ALERT_SCHEMAS = {
       "buy": BuyAlert,
       "trim": TrimAlert,
       "exit": ExitAlert,
       "stop_update": StopUpdateAlert,
       "null": CommentaryAlert,
   }
   ```

5. **Update _standardize_action()**:
   - Add: `stop_update`, `move_stop`, `moving_stop`, `update_stop`, `set_stop` -> "stop_update"

### Parser-Specific Cleanup

**IanParser (`channels/ian.py`)**:
- Remove hardcoded `entry['new_stop'] = 'b/e'` - let schema validator handle
- Schema will normalize LOD, OP, b/e values

**RyanParser (`channels/ryan.py`)**:
- No changes needed - `price: "market"` will now pass validation

**FiFi/Sean**:
- Review prompts to ensure `"market"` mentioned for exits without price

## User Notes
- Analysis done with Gemini on 2026-02-12
- `stop_update` action not yet handled by trade_executor (future task)
- Focus on schema standardization first, executor handling later

## Work Log
- [2026-02-12] Task created based on Gemini codebase analysis
