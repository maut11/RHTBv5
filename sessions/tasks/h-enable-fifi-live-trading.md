---
name: h-enable-fifi-live-trading
branch: none
status: pending
created: 2026-02-03
---

# Enable FiFi Live Trading

## Problem/Goal
FiFi's channel parser is currently in tracking-only mode (`min_trade_contracts=0`). Enable live trading for FiFi with conservative sizing: 5% of total portfolio per full-size trade, minimum 1 contract.

## Changes Required

### 1. Update FiFi config in `config.py` (lines 124-141)
- `test_id`: `1402850612995031090` → `1468477705270988833` (new sim channel)
- `min_trade_contracts`: `0` → `1` (enable trading, min 1 contract)
- `multiplier`: `1.0` → `0.5` (5% portfolio: `MAX_PCT_PORTFOLIO(0.10) * multiplier(0.5) = 5%`)

### 2. Per-channel minimum contracts in `trade_executor.py` (line 888)
Currently the global `MIN_CONTRACTS = 2` overrides everything:
```python
contracts = max(MIN_CONTRACTS, min(calculated_contracts, MAX_CONTRACTS))
```
This would force FiFi to trade 2 contracts minimum despite `min_trade_contracts: 1`. Need to use the channel's `min_trade_contracts` as the floor when it's > 0, instead of the global `MIN_CONTRACTS`.

## Success Criteria
- [ ] FiFi sim channel ID updated to `1468477705270988833`
- [ ] FiFi `min_trade_contracts` set to 1
- [ ] FiFi `multiplier` set to 0.5 (5% portfolio sizing)
- [ ] `trade_executor.py` uses per-channel `min_trade_contracts` as minimum floor (not global `MIN_CONTRACTS`)
- [ ] Sean channel unaffected (still uses `min_trade_contracts: 2` as its floor)
- [ ] Bot starts successfully

## Context Manifest
<!-- Added by context-gathering agent -->

## User Notes
- FiFi sim channel: 1468477705270988833
- 5% of total portfolio size for full-size trades
- Minimum 1 contract per trade

## Work Log
<!-- Updated as work progresses -->
