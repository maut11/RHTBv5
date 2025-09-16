---
task: h-fix-robinhood-api-errors
branch: fix/robinhood-api-errors
status: pending
created: 2025-09-15
modules: [trader.py, channels, robinhood]
---

# Fix Critical Robinhood API Errors

## Problem/Goal

Critical trading system failures due to Robinhood API integration issues:

### Issue 1: Position Detection Failure (Sean's NIO Trim)
- Bot could not detect existing NIO position using Robinhood API
- Error: "Missing contract info for Sean" 
- Trade rejected despite having actual position

### Issue 2: Order Placement Failures (Ryan's SPX)
- SPX orders failing with pricing errors
- Error: "Prices above $1.00 can't have subpenny increments"
- Symbol mapping issues (SPX → SPXW)
- Market hours validation problems

### Root Cause Analysis Needed
Comprehensive audit of all RobinStocks function usage to identify:
- Input format mismatches
- Missing required attributes
- API documentation drift
- Implementation gaps

## Success Criteria
- [ ] Complete audit of all RobinStocks functions used in codebase
- [ ] Document input requirements vs actual inputs for each function
- [ ] Identify and fix position detection failures (NIO case)
- [ ] Resolve order placement pricing errors (SPX case)
- [ ] Fix symbol mapping issues (SPX/SPXW)
- [ ] Validate market hours handling
- [ ] Update API calls to match current RobinStocks documentation
- [ ] Test with actual trades to verify fixes
- [ ] Document corrected API usage patterns

## Context Manifest

### How Robinhood API Integration Currently Works

The trading system integrates with Robinhood through the `robin_stocks` library with sophisticated error handling and multiple fallback mechanisms. When a trading alert comes in, the system follows this complex flow:

**Entry Point Flow:**
1. Discord messages trigger `EnhancedMyClient.on_message()` in `complete_bot.py`
2. Messages are processed by channel-specific parsers (Ryan, Sean, Eva, etc.) in `channels/` directory
3. Parsed trades flow to `TradeExecutor.process_trade()` in `trade_executor.py` 
4. Trade execution delegates to `EnhancedRobinhoodTrader` methods in `trader.py`

**RobinStocks Function Usage Patterns:**
The system uses these core robin_stocks functions with specific input/output expectations:

1. **Authentication:** `r.login(username, password, expiresIn, store_session)`
2. **Account Data:** `r.load_account_profile()`, `r.load_portfolio_profile()`, `r.get_open_option_positions()`
3. **Market Data:** `r.get_option_market_data(symbol, expiration, strike, option_type)`, `r.get_instruments_by_symbols(symbol)`
4. **Order Placement:** `r.order_buy_option_limit()`, `r.order_sell_option_limit()`, `r.order_sell_option_stop_limit()`
5. **Order Management:** `r.get_option_order_info(order_id)`, `r.cancel_option_order(order_id)`

**Position Detection Architecture:**
The system has a three-tier fallback approach for detecting existing positions:

1. **Primary:** `PositionManager` maintains local cache of active positions in `tracked_contracts_live.json`
2. **Secondary:** `PerformanceTracker` SQL database lookup by ticker/channel combination
3. **Tertiary:** `RobinhoodPositionFallback` class queries live Robinhood API via `r.get_open_option_positions()`

When a trim/exit action is received without complete contract details, the system searches through these layers sequentially. The position detection logic in `trader.py:find_open_option_position()` uses symbol variant matching to handle SPX ↔ SPXW conversions.

**Symbol Mapping System:**
Critical to the API integration is the symbol normalization system in `config.py`. The trader symbol (what users say) gets converted to broker symbol (what Robinhood expects):
- `SPX` → `SPXW` (SPX weekly options trade as SPXW on Robinhood)
- Uses `get_broker_symbol()` before API calls, `get_trader_symbol()` for display
- All symbol variants are searched during position matching via `get_all_symbol_variants()`

**Order Execution with Enhanced Pricing:**
The system performs sophisticated price discovery before placing orders:

1. **Buy Orders:** Uses `r.get_option_market_data()` to get `high_fill_rate_buy_price` or falls back to ask price + tick rounding
2. **Sell Orders:** Attempts to get `high_fill_rate_sell_price`, mark price, bid/ask midpoint, or bid price in priority order
3. **Tick Size Validation:** `get_instrument_tick_size()` calls `r.get_instruments_by_symbols()` to get `min_tick_size` field
4. **Price Rounding:** `round_to_tick()` ensures prices comply with exchange tick size rules

**Market Data API Call Pattern:**
Market data calls follow this structure: `r.get_option_market_data(broker_symbol, expiration, strike, option_type)` where:
- `broker_symbol` is post-normalization (e.g., "SPXW" not "SPX")
- `expiration` format is "YYYY-MM-DD" 
- `strike` is float/int value
- `option_type` is "call" or "put" (lowercase)

The response is typically `[[{market_data_dict}]]` (nested arrays) containing fields like `mark_price`, `bid_price`, `ask_price`, `high_fill_rate_buy_price`, `volume`, `open_interest`.

**Error Handling and Retry Logic:**
The system implements multiple retry mechanisms:
- `place_option_sell_order_with_timeout_retry()` retries failed orders with progressive pricing adjustments
- Connection errors trigger `reconnect()` with exponential backoff
- Order validation occurs via `validate_order_requirements()` before execution
- Tick size errors trigger cache clearing and retry with different tick size strategies

### Critical Issues Based on Error Examples

**Issue 1: NIO Position Detection Failure**
The error "Missing contract info for Sean" indicates the three-tier position detection system all failed:
1. Local position cache didn't contain NIO contract details
2. Performance tracker had no open trades for NIO in Sean's channel 
3. Robinhood API position lookup either failed or returned insufficient data

This suggests either: (a) the position was never properly recorded locally, (b) symbol mapping failed between user input and API response, or (c) the Robinhood API position data structure doesn't match expectations in `robinhood_positions.py`.

**Issue 2: SPX Order Pricing Errors** 
The "Prices above $1.00 can't have subpenny increments" error indicates tick size validation failure. The current tick size detection in `get_instrument_tick_size()` has these potential failure points:
1. `r.get_instruments_by_symbols("SPXW")` returns `min_tick_size: None` 
2. Options-specific tick size detection `_get_options_tick_size()` fails
3. Fallback logic uses incorrect 0.05 tick size for high-priced SPX options

SPX options >$1.00 typically require 0.10 tick increments, but the system may be defaulting to 0.05 or using stale cached values.

**Issue 3: Market Hours Trading Conflicts**
The 18:52 trading time suggests extended hours trading, but market data or order placement may have different validation rules outside standard hours.

### For New Implementation: API Audit Requirements

To fix these issues systematically, we need to audit every RobinStocks function call for:

1. **Input Format Validation:** Ensure all parameters match current RobinStocks documentation expectations
2. **Response Structure Handling:** Verify the code handles actual API response formats (nested arrays vs direct objects)
3. **Error Response Processing:** Check that error handling covers all documented error conditions
4. **Symbol Mapping Completeness:** Validate symbol conversion works for all supported instruments
5. **Tick Size Edge Cases:** Test tick size detection for various price ranges and instrument types

### Technical Reference Details

#### Core RobinStocks Function Signatures

```python
# Authentication
r.login(username: str, password: str, expiresIn: int = 86400, store_session: bool = True) -> dict

# Market Data  
r.get_option_market_data(inputSymbols: str, expirationDate: str, strikePrice: float, optionType: str) -> list
r.get_instruments_by_symbols(inputSymbols: str) -> list

# Position Management
r.get_open_option_positions() -> list
r.get_option_order_info(orderID: str) -> dict

# Order Placement
r.order_buy_option_limit(positionEffect: str, creditOrDebit: str, price: float, symbol: str, 
                        quantity: int, expirationDate: str, strike: float, optionType: str, 
                        timeInForce: str = 'gfd') -> dict
                        
r.order_sell_option_limit(positionEffect: str, creditOrDebit: str, price: float, symbol: str,
                         quantity: int, expirationDate: str, strike: float, optionType: str,
                         timeInForce: str = 'gtc') -> dict
```

#### Expected Data Structures

**Market Data Response:**
```python
[[{
    'mark_price': '2.50',
    'bid_price': '2.45', 
    'ask_price': '2.55',
    'high_fill_rate_buy_price': '2.52',
    'high_fill_rate_sell_price': '2.48',
    'volume': '1250',
    'open_interest': '5000',
    'delta': '0.65',
    'gamma': '0.12'
}]]
```

**Instrument Data Response:**
```python
[{
    'min_tick_size': '0.05',
    'symbol': 'SPXW',
    'type': 'option',
    'tradable_chain_id': 'abc-123'
}]
```

#### Configuration Requirements

**Symbol Mappings (config.py):**
```python
SYMBOL_MAPPINGS = {
    "SPX": "SPXW",  # Critical for SPX option trading
}
```

**Channel Configuration:**
```python
CHANNELS_CONFIG = {
    "Sean": {
        "live_id": 1072555808832888945,
        "min_trade_contracts": 1,  # 0 = tracking only mode
    }
}
```

#### File Locations

- **Primary API Integration:** `/Users/mautasmhussan/RHTBv5/trader.py` (EnhancedRobinhoodTrader class)
- **Symbol Mapping Logic:** `/Users/mautasmhussan/RHTBv5/config.py` (SYMBOL_MAPPINGS, get_broker_symbol())
- **Position Detection:** `/Users/mautasmhussan/RHTBv5/robinhood_positions.py` (RobinhoodPositionFallback)
- **Trade Execution:** `/Users/mautasmhussan/RHTBv5/trade_executor.py` (TradeExecutor class)
- **Market Data Testing:** `/Users/mautasmhussan/RHTBv5/test_spx_market_data.py` (SPX-specific debugging)
- **Order Validation:** `/Users/mautasmhussan/RHTBv5/trader.py:615-660` (validate_order_requirements method)

## Context Files

## User Notes

**Specific Error Examples:**

1. **NIO Position Detection (2025-09-15 13:31:22)**
   ```
   🎯 Processing trim trade: {'action': 'trim', 'ticker': 'NIO', 'price': 0.75, 'channel_id': 1072555808832888945, 'received_ts': '2025-09-15T13:31:22.868287+00:00'}
   ❌ Missing contract info for Sean: {'action': 'trim', 'ticker': 'NIO', 'price': 0.75, 'channel_id': 1072555808832888945, 'received_ts': '2025-09-15T13:31:22.868287+00:00', 'channel': 'Sean', 'trader_symbol': 'NIO', 'broker_symbol': 'NIO', 'strike': None, 'expiration': None, 'type': None}
   📊 Trade Summary: No position found
   ```

2. **SPX Order Failure (2025-09-15 18:52:21)**
   ```
   Buy order failed: {'price': ["Prices above $1.00 can't have subpenny increments."]}
   Trading outside market hours: 18:52
   Buy order preparation: SPX/SPXW $6605P x1 @ $2.29
   ```

**Action Required:** 
Systematic review of every RobinStocks function call in the codebase to identify format mismatches and missing attributes.

## RobinStocks API Audit Results

### Summary
Comprehensive audit of all robin_stocks function usage reveals **mostly correct implementation** with several critical data handling issues that explain the trading failures.

### Function-by-Function Analysis

#### Authentication Functions
- **`r.login()`** ✅ Correct implementation 
  - ⚠️ **Issue**: No 2FA/MFA support - could cause auth failures
- **`r.logout()`** ✅ Correct implementation
- **`r.load_account_profile()`** ✅ Correct with proper error handling
- **`r.load_portfolio_profile()`** ✅ Correct with equity validation

#### Position & Market Data Functions  
- **`r.get_open_option_positions()`** ✅ Correct implementation
- **`r.get_option_market_data()`** ⚠️ **Critical Issue**: Inconsistent data structure
  - Sometimes returns `[[data]]`, sometimes `[data]`
  - Code handles inconsistently: `market_data[0][0]` vs `market_data[0]`
  - **Root cause of position detection failures**
- **`r.get_instruments_by_symbols()`** ✅ Correct with good error recovery
- **`r.get_quotes()`** ✅ Correct implementation
- **`r.get_option_quotes()`** ✅ Correct fallback mechanism

#### Order Functions
- **`r.order_buy_option_limit()`** ✅ Correct with all required parameters
- **`r.order_sell_option_limit()`** ✅ Correct with proper timeInForce
- **`r.order_sell_option_stop_limit()`** ✅ Correct stop/limit price handling
- **`r.cancel_option_order()`** ✅ Correct implementation
- **`r.get_option_order_info()`** ✅ Correct for order monitoring
- **`r.get_all_open_option_orders()`** ✅ Correct implementation

#### Utility Functions
- **`r.request_get()`** ✅ Correct for instrument data fetching
- **`r.get_option_market_data_by_id()`** ✅ Correct for debugging

### Critical Issues Identified

#### 1. Inconsistent Market Data Structure (HIGH PRIORITY)
**Problem**: `r.get_option_market_data()` returns different formats:
- Format A: `[[data]]` - requires `market_data[0][0]`
- Format B: `[data]` - requires `market_data[0]`

**Impact**: 
- NIO position detection failures
- SPX pricing calculation errors
- Unpredictable behavior across different symbols/times

**Solution Needed**: Centralized data structure normalization function

#### 2. Missing 2FA Support (MEDIUM PRIORITY)
**Problem**: Code explicitly doesn't support MFA/2FA
**Impact**: Authentication failures if account has 2FA enabled
**Solution Needed**: Implement MFA code handling or document requirement

#### 3. Price Precision Issues (MEDIUM PRIORITY)
**Problem**: Floating-point calculations for financial data
**Impact**: SPX "subpenny increments" errors for prices >$1.00
**Solution Needed**: Use Decimal class for price calculations

#### 4. No Rate Limiting (LOW PRIORITY)
**Problem**: No explicit rate limiting on API calls
**Impact**: Potential temporary API blocks during high activity
**Solution Needed**: Implement request throttling

### Strengths Found
✅ **Symbol Normalization**: Excellent SPX/SPXW mapping
✅ **Error Handling**: Comprehensive retry and recovery logic  
✅ **Tick Size Logic**: Advanced SPX 0DTE detection
✅ **Parameter Usage**: All required parameters correctly provided
✅ **Fallback Systems**: Smart position detection fallbacks

### Next Steps
1. Fix market data structure inconsistency (addresses NIO/SPX issues)
2. Add price precision handling with Decimal class
3. Consider 2FA support for authentication robustness

## Work Log
<!-- Updated as work progresses -->
- [2025-09-15] Created task after massive trading failures
- [2025-09-15] Issues identified: NIO position detection, SPX order placement
- [2025-09-15] Completed comprehensive RobinStocks API audit
- [2025-09-15] Identified market data structure inconsistency as root cause