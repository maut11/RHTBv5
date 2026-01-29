---
name: m-implement-command-expansion
branch: feature/command-expansion
status: pending
created: 2026-01-28
---

# Expand Discord Bot Commands

## Problem/Goal
Enhance the RHTBv5 Discord bot commands to provide more comprehensive trading information and match the functionality of the old RHTBv6 bot. Currently, commands provide basic information but lack the depth needed for serious options trading.

**Commands to implement/enhance:**
1. **Enhance `!portfolio`** - Add buying power alongside portfolio value
2. **Add `!pnl [days]`** - P&L summary with win rate, avg hold time, best/worst trade
3. **Enhance `!getprice` → `!price`** - Add Greeks (Δ, Γ, Θ, V, ρ), IV, volume, open interest
4. **Enhance `!positions`** - Show entry price, current price, P&L per position

## Success Criteria

### `!portfolio` Enhancement
- [ ] Shows portfolio value AND buying power
- [ ] Displays formatted currency values

### `!pnl [days]` Command
- [ ] Accepts optional days parameter (default 30)
- [ ] Shows total P&L in dollars
- [ ] Shows total trades count
- [ ] Shows win rate percentage
- [ ] Shows winning/losing trade counts
- [ ] Shows average P&L per trade
- [ ] Shows best and worst trade
- [ ] Shows average hold time

### `!price` Command (Enhanced `!getprice`)
- [ ] Parses natural language option queries (existing AI parsing)
- [ ] Shows mark, bid, ask prices and spread
- [ ] Shows Greeks: Delta, Gamma, Theta, Vega, Rho
- [ ] Shows volume and open interest
- [ ] Shows implied volatility (IV)
- [ ] Shows price change from previous close
- [ ] `!getprice` works as alias for backward compatibility

### `!positions` Enhancement
- [ ] Shows entry price (average cost) per position
- [ ] Shows current price (mark) per position
- [ ] Shows P&L in dollars and percentage per position
- [ ] Shows total portfolio P&L summary

## Context Manifest
<!-- Added by context-gathering agent -->

### How Discord Commands Currently Work

The RHTBv5 Discord bot operates as a self-bot using a user token (via `discord.py`). When a message arrives in the command channel (ID: `1401792635483717747`), the bot's `on_message` handler checks if it starts with `!` and routes it to `handle_command()` in `complete_bot.py`.

The command handling flow begins at line 1752 in `EnhancedMyClient.handle_command()`. The method extracts the command and arguments from `message.content.split()`, then uses a series of `if/elif` conditions to dispatch to the appropriate handler. Commands send responses via the alert queue system using `alert_queue.add_alert(COMMANDS_WEBHOOK, payload, alert_type)`.

**Current command implementations:**

1. **`!portfolio`** (lines 2028-2031): Currently only shows portfolio value
   ```python
   elif command == "!portfolio":
       await alert_queue.add_alert(COMMANDS_WEBHOOK, {"content": "... Fetching live account portfolio value..."}, "command_response")
       portfolio_value = await self.loop.run_in_executor(None, live_trader.get_portfolio_value)
       await alert_queue.add_alert(COMMANDS_WEBHOOK, {"content": f"... **Total Portfolio Value:** ${portfolio_value:,.2f}"}, "command_response")
   ```

2. **`!positions`** (lines 2023-2026): Shows basic position list via `get_positions_string()`
   ```python
   elif command == "!positions":
       await alert_queue.add_alert(COMMANDS_WEBHOOK, {"content": "... Fetching live account positions..."}, "command_response")
       pos_string = await self.get_positions_string()
       await alert_queue.add_alert(COMMANDS_WEBHOOK, {"content": f"**Current Positions:**\n```\n{pos_string}\n```"}, "command_response")
   ```

3. **`!getprice`** (lines 1882-1890): Price lookup using AI parsing
   ```python
   elif command == "!getprice":
       query = content[len("!getprice"):].strip()
       if not query:
           await alert_queue.add_alert(COMMANDS_WEBHOOK, {...}, "command_response")
           return
       await self._handle_get_price(query)
       return
   ```

4. **`!trades`** (lines 1857-1879): Shows recent completed trades (basic P&L display)

**Helper method for positions** (`get_positions_string()` at lines 2044-2062):
```python
async def get_positions_string(self) -> str:
    positions = await self.loop.run_in_executor(None, live_trader.get_open_option_positions)
    if not positions:
        return "No open option positions."

    holdings = []
    for p in positions:
        try:
            instrument_data = await self.loop.run_in_executor(None, live_trader.get_option_instrument_data, p['option'])
            if instrument_data:
                holdings.append(f"* {p['chain_symbol']} {instrument_data['expiration_date']} {instrument_data['strike_price']}{instrument_data['type'].upper()[0]} x{int(float(p['quantity']))}")
        except Exception as e:
            print(f"Could not process a position: {e}")

    return "\n".join(holdings) if holdings else "No processable option positions found."
```

### How the Trader Interface Gets Market Data

The `RobinhoodTrader` class in `/Users/mautasimhussain/trading-bots/RHTBv5/trader.py` wraps `robin_stocks.robinhood` to provide market data access. The key method for options data is:

**`get_option_market_data()`** (lines 1092-1109):
```python
def get_option_market_data(self, symbol, expiration, strike, opt_type):
    """Get market data with symbol mapping"""
    try:
        if not self.ensure_connection():
            return []

        # Normalize symbol for broker
        broker_symbol = self.normalize_symbol_for_broker(symbol)

        data = r.get_option_market_data(broker_symbol, expiration, strike, opt_type)
        if data:
            print(f"... Market data retrieved for {symbol}/{broker_symbol} ${strike}{opt_type.upper()}")
            logger.debug(f"Market data retrieved for {symbol}/{broker_symbol}")
        return data
    except Exception as e:
        print(f"... Error fetching market data for {symbol}: {e}")
        logger.error(f"Market data exception: {e}")
        return []
```

**Market data response structure** (from Robin Stocks API):
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
    'gamma': '0.12',
    'theta': '-0.05',
    'vega': '0.08',
    'implied_volatility': '0.35',
    'previous_close_price': '2.40',
    'rho': '0.02'
}]]
```

**CRITICAL**: The response is nested as `[[{data}]]` (double-nested list). The codebase has a helper `_normalize_market_data()` at lines 475-495 that handles this:

```python
def _normalize_market_data(self, market_data) -> dict:
    """Normalize market data response to handle [[data]] vs [data] inconsistency"""
    try:
        if not market_data or len(market_data) == 0:
            return None

        # Handle [[data]] format (nested array)
        if isinstance(market_data[0], list):
            if len(market_data[0]) > 0 and isinstance(market_data[0][0], dict):
                return market_data[0][0]
            else:
                return None

        # Handle [data] format (single array)
        elif isinstance(market_data[0], dict):
            return market_data[0]

        return None

    except (IndexError, TypeError):
        return None
```

**Account methods for buying power:**

**`get_buying_power()`** (lines 270-286):
```python
def get_buying_power(self) -> float:
    """Get available buying power with error handling"""
    try:
        if not self.ensure_connection():
            return 0.0

        account = r.load_account_profile()
        if account:
            buying_power = float(account.get('buying_power', 0))
            print(f"... Available buying power: ${buying_power:,.2f}")
            logger.debug(f"Buying power: ${buying_power:,.2f}")
            return buying_power
        return 0.0
    except Exception as e:
        print(f"... Error fetching buying power: {e}")
        logger.error(f"Buying power exception: {e}")
        return 0.0
```

**`get_portfolio_value()`** (lines 245-268):
```python
def get_portfolio_value(self) -> float:
    """Get current portfolio value with enhanced error handling"""
    try:
        if not self.ensure_connection():
            return 0.0

        profile = r.load_portfolio_profile()
        if profile and 'equity' in profile:
            equity = float(profile['equity'])
            return equity
        else:
            return 0.0
    except Exception as e:
        return 0.0
```

### How Performance Tracking Works for P&L Data

The `EnhancedPerformanceTracker` class in `/Users/mautasimhussain/trading-bots/RHTBv5/performance_tracker.py` maintains a SQLite database at `logs/performance_tracking.db` with these key tables:

**`trades` table schema** (lines 87-113):
```sql
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE NOT NULL,
    channel TEXT NOT NULL,
    channel_id INTEGER,
    ticker TEXT NOT NULL,
    strike REAL NOT NULL,
    option_type TEXT NOT NULL,
    expiration TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT,
    entry_price REAL NOT NULL,
    exit_price REAL,
    quantity INTEGER NOT NULL,
    quantity_remaining INTEGER DEFAULT 0,
    size_category TEXT NOT NULL,
    pnl_dollars REAL,
    pnl_percent REAL,
    status TEXT NOT NULL DEFAULT 'open',
    stop_loss_price REAL,
    trailing_stop_active INTEGER DEFAULT 0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
)
```

**Key methods for P&L summary:**

**`get_channel_performance()`** (lines 600-679) - Returns comprehensive performance metrics:
```python
def get_channel_performance(self, channel: str, days: int = 30) -> Dict[str, Any]:
    # Returns:
    {
        'channel': channel,
        'total_trades': total_trades,
        'winning_trades': len(winning_trades),
        'losing_trades': len(losing_trades),
        'win_rate': win_rate,
        'avg_return': avg_return,
        'total_pnl': total_pnl,
        'best_trade': best_trade,
        'worst_trade': worst_trade,
        'sharpe_ratio': sharpe_ratio,
        'days_analyzed': days,
        'recent_trades': trades[:5]
    }
```

**`get_performance_summary()`** (lines 859-926) - Aggregated stats from performance_summary table:
```python
def get_performance_summary(self, channel: str = None, days: int = 30) -> Dict[str, Any]:
    # Returns aggregated data from performance_summary table
    {
        'channel': channel or 'All Channels',
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': (winning_trades / total_trades * 100),
        'total_pnl': result['total_pnl'] or 0,
        'best_trade': result['best_trade'] or 0,
        'worst_trade': result['worst_trade'] or 0,
        'days_analyzed': days
    }
```

**`get_recent_trades()`** (lines 571-598) - Gets recent closed trades:
```python
def get_recent_trades(self, limit: int = 10, channel: str = None) -> List[Dict]:
    # Returns list of trade dicts with all columns from trades table
```

**Calculating average hold time**: The `trades` table stores `entry_time` and `exit_time` as ISO timestamps. To calculate average hold time:
```python
hold_time = datetime.fromisoformat(exit_time) - datetime.fromisoformat(entry_time)
```

### How Price Parser Works for !getprice Command

The `_handle_get_price()` method (lines 2064-2141) handles the price lookup flow:

1. **Parses query using PriceParser** - Uses OpenAI to extract contract details (ticker, strike, type, expiration)
2. **Calls `trader.get_option_market_data()`** to fetch live market data
3. **Normalizes the response** using the nested array handling logic
4. **Formats and sends response** via alert queue

Current response fields extracted (lines 2119-2136):
```python
bid = float(data.get('bid_price', 0) or 0)
ask = float(data.get('ask_price', 0) or 0)
mark = float(data.get('mark_price', 0) or 0)
volume = int(data.get('volume', 0) or 0)
open_interest = int(data.get('open_interest', 0) or 0)
```

**Available fields in market data (not currently displayed):**
- `delta` - Delta Greek
- `gamma` - Gamma Greek
- `theta` - Theta Greek
- `vega` - Vega Greek
- `rho` - Rho Greek
- `implied_volatility` - IV percentage
- `previous_close_price` - Previous close for change calculation

### Position Data Structure from Robinhood

**`get_open_option_positions()`** returns list of positions (lines 865-885):
```python
def get_open_option_positions(self):
    """Get open positions with enhanced symbol mapping"""
    positions = r.get_open_option_positions()
    # Each position has: chain_symbol, quantity, option (URL), average_price, etc.
    for position in positions:
        broker_symbol = position.get('chain_symbol', '')
        trader_symbol = self.normalize_symbol_from_broker(broker_symbol)
        position['trader_symbol'] = trader_symbol
        position['broker_symbol'] = broker_symbol
    return positions
```

**Position data structure:**
```python
{
    'chain_symbol': 'SPY',           # or 'SPXW' for SPX
    'quantity': '5.0000',            # String of float
    'average_price': '1.5000',       # Entry price (string)
    'option': 'https://api.robinhood.com/options/instruments/XXX/',  # URL
    'trader_symbol': 'SPY',          # Added by normalization
    'broker_symbol': 'SPY'           # Added by normalization
}
```

**`get_option_instrument_data(url)`** returns contract details (line 916-926):
```python
{
    'strike_price': '500.0',
    'expiration_date': '2026-01-31',
    'type': 'call'  # or 'put'
}
```

### Existing Command Patterns to Follow

All commands follow this pattern:
1. Send "processing" message to user
2. Execute blocking operations in thread pool via `run_in_executor`
3. Format response as plain text or embed
4. Send response via `alert_queue.add_alert()`

**Embed format example** (from `!status` at lines 1795-1831):
```python
status_embed = {
    "title": "... RHTB v4 Enhanced Status",
    "color": 0x00ff00,
    "fields": [
        {
            "name": "... Configuration",
            "value": f"**Simulation:** {'ON' if SIM_MODE else 'OFF'}\n...",
            "inline": True
        },
        # More fields...
    ],
    "timestamp": datetime.now(timezone.utc).isoformat()
}
await alert_queue.add_alert(COMMANDS_WEBHOOK, {"embeds": [status_embed]}, "command_response")
```

### Technical Reference Details

#### Key Function Signatures

**Trader interface:**
```python
# trader.py (EnhancedRobinhoodTrader)
def get_portfolio_value(self) -> float
def get_buying_power(self) -> float
def get_option_market_data(self, symbol: str, expiration: str, strike: float, opt_type: str) -> list
def get_open_option_positions(self) -> list
def get_option_instrument_data(self, url: str) -> dict
def normalize_symbol_for_broker(self, symbol: str) -> str
```

**Performance tracker:**
```python
# performance_tracker.py (EnhancedPerformanceTracker)
def get_recent_trades(self, limit: int = 10, channel: str = None) -> List[Dict]
def get_channel_performance(self, channel: str, days: int = 30) -> Dict[str, Any]
def get_performance_summary(self, channel: str = None, days: int = 30) -> Dict[str, Any]
```

**Price parser:**
```python
# channels/price_parser.py (PriceParser)
def parse_query(self, query: str, logger) -> dict  # Returns {ticker, strike, type, expiration}
```

#### Data Structures

**Market data response fields:**
| Field | Type | Description |
|-------|------|-------------|
| mark_price | str | Mark (mid) price |
| bid_price | str | Best bid |
| ask_price | str | Best ask |
| volume | str | Daily volume |
| open_interest | str | Open interest |
| delta | str | Delta Greek |
| gamma | str | Gamma Greek |
| theta | str | Theta Greek |
| vega | str | Vega Greek |
| rho | str | Rho Greek |
| implied_volatility | str | IV as decimal |
| previous_close_price | str | Previous close |

#### File Locations

- **Command handlers:** `/Users/mautasimhussain/trading-bots/RHTBv5/complete_bot.py:1752-2062` (EnhancedMyClient.handle_command)
- **Trader interface:** `/Users/mautasimhussain/trading-bots/RHTBv5/trader.py` (EnhancedRobinhoodTrader class)
- **Performance tracker:** `/Users/mautasimhussain/trading-bots/RHTBv5/performance_tracker.py` (EnhancedPerformanceTracker class)
- **Price parser:** `/Users/mautasimhussain/trading-bots/RHTBv5/channels/price_parser.py` (PriceParser class)
- **Config:** `/Users/mautasimhussain/trading-bots/RHTBv5/config.py` (webhooks, symbol mappings)

#### Implementation Patterns

**Pattern for new command with blocking API call:**
```python
elif command == "!newcommand":
    # 1. Send processing message
    await alert_queue.add_alert(COMMANDS_WEBHOOK, {"content": "... Processing..."}, "command_response")

    # 2. Define blocking function
    def blocking_operation():
        # Call trader methods or database queries
        data = trader.get_some_data()
        return data

    # 3. Execute in thread pool
    result = await self.loop.run_in_executor(None, blocking_operation)

    # 4. Format response
    embed = {
        "title": "...",
        "fields": [...],
        "color": 0x00ff00
    }

    # 5. Send response
    await alert_queue.add_alert(COMMANDS_WEBHOOK, {"embeds": [embed]}, "command_response")
```

**Greek display formatting convention:**
```python
# Use Greek symbols in output
delta_symbol = "..."  # Delta
gamma_symbol = "..."  # Gamma
theta_symbol = "..."  # Theta
vega_symbol = "V"     # Vega (no Greek symbol commonly used)
rho_symbol = "..."    # Rho
```

### What Needs to Connect for Each Enhancement

#### 1. `!portfolio` Enhancement
- Add call to `trader.get_buying_power()` alongside `get_portfolio_value()`
- Display both values formatted with currency

#### 2. `!pnl [days]` Command
- Parse optional days parameter (default 30)
- Call `performance_tracker.get_performance_summary(days=days)` or create new method
- Query trades table for: total P&L, trade count, win rate, best/worst trade
- Calculate average hold time from entry_time/exit_time

#### 3. `!price` Command (Enhanced `!getprice`)
- Keep existing AI parsing flow
- Add `!getprice` as alias for backward compatibility
- Extract and display Greeks from market data response (delta, gamma, theta, vega, rho)
- Extract and display IV from implied_volatility field
- Calculate and display price change from previous_close_price
- Volume and open interest already extracted but ensure display

#### 4. `!positions` Enhancement
- For each position, fetch current market data via `get_option_market_data()`
- Calculate P&L: `(current_mark - average_price) * quantity * 100`
- Display entry price (average_price from position)
- Display current price (mark_price from market data)
- Sum for total portfolio P&L

## User Notes
- Keep `!getprice` as alias for backward compatibility with `!price`
- Data should come from Robinhood API via existing trader interface
- Performance data comes from EnhancedPerformanceTracker

## Work Log
<!-- Updated as work progresses -->
- [2026-01-28] Task created

### 2026-01-28 - Implementation Complete

#### Completed
- Enhanced `!portfolio` command to show portfolio value AND buying power
- Implemented new `!pnl [days]` command with total P&L, win rate, avg hold time, best/worst trade
- Enhanced `!price` command with Greeks, IV, and price change
- Kept `!getprice` as backward-compatible alias
- Enhanced `!positions` to show entry price, current price, and P&L per position
- Updated `!help` command to document all new/enhanced commands
- Feature branch merged to main

#### Files Modified
- `main.py` - All command handler implementations

#### Documentation Updates
- Added Discord Bot Commands section to `CLAUDE.md` documenting:
  - Trading commands table (!price, !pnl, !positions, !portfolio, !trades, !mintick, !clear)
  - System commands table (!status, !heartbeat, !sim, !testing)
  - Alert system commands table (!alert_health, !alert_restart, !alert_test, !queue, !help)
  - Command implementation details with handler method references
  - Price command response fields (Greeks, market data)
