# config.py - RHTB v4 Configuration with Per-Channel Padding
MAX_PCT_PORTFOLIO = 0.05
MAX_DOLLAR_AMOUNT = 20000
MIN_TRADE_QUANTITY = 3

# Default paddings (can be overridden per channel)
DEFAULT_BUY_PRICE_PADDING = 0.02
DEFAULT_SELL_PRICE_PADDING = 0.01

POSITION_SIZE_MULTIPLIERS = { "lotto": 0.10, "small": 0.25, "half": 0.50, "full": 1.00 }

# Delay for stop loss placement (in seconds)
STOP_LOSS_DELAY_SECONDS = 900  # 15 minutes

# --- v4 CHANNEL CONFIGURATION with Individual Padding ---
CHANNELS_CONFIG = {
    "Ryan": {
        "live_id": 1072559822366576780, # ryan-alerts
        "test_id": 1396011198343811102, # <-- REPLACE WITH YOUR RYAN SIMULATION CHANNEL ID
        "parser": "RyanParser",
        "multiplier": 1.0,
        "initial_stop_loss": 0.35,  # 50% stop loss
        "trailing_stop_loss_pct": 0.20,
        "buy_padding": 0.05,  # 2% padding for buys
        "sell_padding": 0.025,  # 1% padding for sells
        "model": "gpt-4o-2024-08-06",
        "color": 3447003  # Blue
    },
    "Eva": {
        "live_id": 1072556084662902846, # evas-plays
        "test_id": 1399289540484530247, # <-- REPLACE WITH YOUR EVA SIMULATION CHANNEL ID
        "parser": "EvaParser",
        "multiplier": 1,
        "initial_stop_loss": 0.30,
        "trailing_stop_loss_pct": 0.20,
        "buy_padding": 0.025,  # 1.5% padding for buys
        "sell_padding": 0.025,  # 0.5% padding for sells
        "model": "gpt-4o-2024-08-06",
        "color": 10181046 # Purple
    },
    "Sean": {
        "live_id": 1072555808832888945, # seans-plays
        "test_id": 1398211580470235176, # <-- REPLACE WITH YOUR SEAN SIMULATION CHANNEL ID
        "parser": "SeanParser",
        "multiplier": 1.0,
        "initial_stop_loss": 0.50,
        "trailing_stop_loss_pct": 0.20,
        "buy_padding": 0.025,  # 2% padding
        "sell_padding": 0.025,  # 1% padding
        "model": "gpt-4o-2024-08-06",
        "color": 3066993  # Green
    },
    "Will": {
        "live_id": 1257442835465244732, # will-alerts
        "test_id": 1398585430617886720, # <-- REPLACE WITH YOUR WILL SIMULATION CHANNEL ID
        "parser": "WillParser",
        "multiplier": 1.0,
        "initial_stop_loss": 0.30,
        "trailing_stop_loss_pct": 0.20,
        "buy_padding": 0.025,  # 2.5% padding
        "sell_padding": 0.025,   # 1% padding
        "model": "gpt-4o-2024-08-06",
        "color": 15105642 # Orange
    },
    "FiFi": {
        "live_id": 1368713891072315483, # fifi-alerts
        "test_id": 1402850612995031090, # <-- REPLACE WITH YOUR FIFI SIMULATION CHANNEL ID
        "parser": "FiFiParser",
        "multiplier": 1.0,
        "initial_stop_loss": 0.50,
        "trailing_stop_loss_pct": 0.20,
        "buy_padding": 0.025,  # 2% padding
        "sell_padding": 0.025,  # 1% padding
        "model": "gpt-4o-2024-08-06",
        "color": 15277667 # Pink
    }
}

# --- PERFORMANCE TRACKING CONFIGURATION ---
PERFORMANCE_DB_FILE = "performance_tracking.db"
PERFORMANCE_CSV_BACKUP = "performance_backup.csv"

# Performance metrics to track
PERFORMANCE_METRICS = {
    "win_rate": "Percentage of profitable trades",
    "average_return": "Average percentage return per trade",
    "total_trades": "Total number of completed trades",
    "total_pnl": "Total profit/loss in dollars",
    "best_trade": "Highest percentage return",
    "worst_trade": "Lowest percentage return",
    "avg_hold_time": "Average time positions are held",
    "success_by_size": "Win rate by position size (lotto/small/half/full)",
    "monthly_performance": "Performance breakdown by month"
}

# Alert formatting configuration
ALERT_CONFIG = {
    "show_timestamps": True,
    "show_user_info": True,
    "show_performance_metrics": True,
    "include_market_context": True,
    "format_currency": True,
    "show_position_sizing": True
}