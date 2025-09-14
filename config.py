# config.py - Enhanced RHTB v4 Configuration with Channel Isolation and Symbol Mapping
MAX_PCT_PORTFOLIO = 0.10
MAX_DOLLAR_AMOUNT = 25000
MIN_TRADE_QUANTITY = 1

# Default paddings (can be overridden per channel)
DEFAULT_BUY_PRICE_PADDING = 0.020
DEFAULT_SELL_PRICE_PADDING = 0.01

POSITION_SIZE_MULTIPLIERS = { 
    "lotto": 0.10, 
    "small": 0.25, 
    "half": 0.50, 
    "full": 1.00 
}

# Enhanced risk management settings
STOP_LOSS_DELAY_SECONDS = 900  # 15 minutes
DEFAULT_INITIAL_STOP_LOSS = 0.50  # 50% loss protection
DEFAULT_TRAILING_STOP_PCT = 0.20  # 20% trailing stop

# ========================================
# SYMBOL MAPPING CONFIGURATION
# ========================================
# Map symbols from what traders say to what brokers use
SYMBOL_MAPPINGS = {
    "SPX": "SPXW",     # SPX trades as SPXW weekly options on Robinhood
    # "NDX": "NDXP",   # NDX options may not be available on Robinhood
    # Add more mappings as discovered
}

# Reverse mapping for position lookups (auto-generated + manual)
REVERSE_SYMBOL_MAPPINGS = {}
for original, broker in SYMBOL_MAPPINGS.items():
    REVERSE_SYMBOL_MAPPINGS[broker] = original

# Additional reverse mappings if needed
REVERSE_SYMBOL_MAPPINGS.update({
    # Can add explicit reverse mappings here if needed
})

def get_broker_symbol(symbol: str) -> str:
    """Convert trader symbol to broker symbol"""
    if not symbol:
        return symbol
    symbol_upper = symbol.upper()
    return SYMBOL_MAPPINGS.get(symbol_upper, symbol_upper)

def get_trader_symbol(broker_symbol: str) -> str:
    """Convert broker symbol back to trader symbol"""
    if not broker_symbol:
        return broker_symbol
    symbol_upper = broker_symbol.upper()
    return REVERSE_SYMBOL_MAPPINGS.get(symbol_upper, symbol_upper)

def get_all_symbol_variants(symbol: str) -> list:
    """Get all possible variants of a symbol for searching"""
    if not symbol:
        return []
    
    variants = set()
    symbol_upper = symbol.upper()
    variants.add(symbol_upper)
    
    # Add broker variant if exists
    if symbol_upper in SYMBOL_MAPPINGS:
        variants.add(SYMBOL_MAPPINGS[symbol_upper])
    
    # Add trader variant if this is a broker symbol
    if symbol_upper in REVERSE_SYMBOL_MAPPINGS:
        variants.add(REVERSE_SYMBOL_MAPPINGS[symbol_upper])
    
    return list(variants)

# ========================================
# WEBHOOK URLS
# ========================================
PLAYS_WEBHOOK = "https://discord.com/api/webhooks/1397759819590537366/WQu-ryRbotOx0Zyz2zH17ls9TGuxeDIZ4T9I3uOlpfwnCswGZrAs5VfHTwHxNWkqXwFw"
ALL_NOTIFICATION_WEBHOOK = "https://discord.com/api/webhooks/1400001289374662787/QsFEWAMTGkKPXZbJXMBPUCRfD1K8x4-_OrT4iY3WqELCzrBdL1DnROT540RsS_4nk8UQ"
LIVE_FEED_WEBHOOK = "https://discord.com/api/webhooks/1404682958564233226/lFCIL_VhoWpdn88fuCyWD4dQ9duTEi_W-0MzIvSrfETy3f9yj-O1Yxgzk1YHOunHLGP5"
COMMANDS_WEBHOOK = "https://discord.com/api/webhooks/1402044700378267800/C2ooBVpV-lyj1COQM2OUH2u8gjNr0QhODrC0qR1leZJAMCQvnxnqrzE7xHUbIDmL8RQ9"
HEARTBEAT_WEBHOOK = "https://discord.com/api/webhooks/1408908444794224880/ABAosRa_i5P_gdID3cV4kkbOGaYo-O1tWEkiskl2HXjtZn9qH7FuRsGsFbTLkDGYLVp0"

# Enhanced Channel Configuration with Strict Isolation
CHANNELS_CONFIG = {
    "Ryan": {
        "live_id": 1072559822366576780,  # ryan-alerts
        "test_id": 1396011198343811102,  # ryan simulation channel
        "parser": "RyanParser",
        "multiplier": 1.0,
        "min_trade_contracts": 1,  # Minimum contracts to trade (0 = no trading)
        "initial_stop_loss": 0.5,  # 35% stop loss for Ryan
        "trailing_stop_loss_pct": 0.20,
        "buy_padding": 0.025,  # 5% padding for buys
        "sell_padding": 0.01,  # 2.5% padding for sells
        "model": "gpt-4o-2024-08-06",
        "color": 3447003,  # Blue
        "description": "Ryan's scalping alerts with tight risk management",
        "risk_level": "medium",
        "typical_hold_time": "5-30 minutes",
        # Symbol remapping specific to Ryan's channel
        "symbol_remapping": {
            "SPX": "SPXW"  # Ryan often uses SPX which trades as SPXW
        },
        # SPEED OPTIMIZATIONS for Ryan's sequential trading style
        "fast_parsing_enabled": True,  # Use regex for TRIM/EXIT
        "trade_first_mode": True,     # Execute trades before alerts
        "use_robinhood_tick_api": True  # Always use live tick sizes
    },
    "Eva": {
        "live_id": 1072556084662902846,  # evas-plays
        "test_id": 1399289540484530247,  # eva simulation channel
        "parser": "EvaParser",
        "multiplier": 1.0,
        "min_trade_contracts": 1,  # Minimum contracts to trade (0 = no trading)
        "initial_stop_loss": 0.5,  # 30% stop loss for Eva
        "trailing_stop_loss_pct": 0.20,
        "buy_padding": 0.025,  # 2.5% padding for buys
        "sell_padding": 0.01,  # 2.5% padding for sells
        "model": "gpt-4o-2024-08-06",
        "color": 10181046,  # Purple
        "description": "Eva's swing trades with momentum focus",
        "risk_level": "medium",
        "typical_hold_time": "30 minutes - 2 hours",
        "trade_first_mode": True     # Execute trades before alerts
    },
    "Sean": {
        "live_id": 1072555808832888945,  # seans-plays
        "test_id": 1398211580470235176,  # sean simulation channel
        "parser": "SeanParser",
        "multiplier": 1.0,
        "min_trade_contracts": 1,  # Minimum contracts to trade (0 = no trading)
        "initial_stop_loss": 0.50,  # 50% stop loss for Sean
        "trailing_stop_loss_pct": 0.20,
        "buy_padding": 0.025,  # 2.5% padding
        "sell_padding": 0.01,  # 2.5% padding
        "model": "gpt-4o-2024-08-06",
        "color": 3066993,  # Green
        "description": "Sean's technical analysis based trades",
        "risk_level": "medium-high",
        "typical_hold_time": "1-4 hours",
        "trade_first_mode": True     # Execute trades before alerts
    },
    "Will": {
        "live_id": 1257442835465244732,  # will-alerts
        "test_id": 1398585430617886720,  # will simulation channel
        "parser": "WillParser",
        "multiplier": 0.5,
        "min_trade_contracts": 0,  # Minimum contracts to trade (0 = no trading)
        "initial_stop_loss": 0.5,  # 30% stop loss for Will
        "trailing_stop_loss_pct": 0.20,
        "buy_padding": 0.025,  # 2.5% padding
        "sell_padding": 0.01,   # 2.5% padding
        "model": "gpt-4o-2024-08-06",
        "color": 15105642,  # Orange
        "description": "Will's day trading strategies",
        "risk_level": "high",
        "typical_hold_time": "15 minutes - 1 hour",
        "trade_first_mode": True     # Execute trades before alerts
    },
    "FiFi": {
        "live_id": 1368713891072315483,  # fifi-alerts
        "test_id": 1402850612995031090,  # fifi simulation channel
        "parser": "FiFiParser",
        "multiplier": 1.0,
        "min_trade_contracts": 0,  # Minimum contracts to trade (0 = no trading)
        "initial_stop_loss": 0.50,  # 50% stop loss for FiFi
        "trailing_stop_loss_pct": 0.20,
        "buy_padding": 0.025,  # 2.5% padding
        "sell_padding": 0.01,  # 2.5% padding
        "model": "gpt-4o-2024-08-06",
        "color": 15277667,  # Pink
        "description": "FiFi's swing and momentum trades",
        "risk_level": "medium",
        "typical_hold_time": "30 minutes - 4 hours",
        "trade_first_mode": True     # Execute trades before alerts
    }
}

# Performance tracking configuration
PERFORMANCE_DB_FILE = "logs/performance_tracking.db"
PERFORMANCE_CSV_BACKUP = "performance_backup.csv"

# Enhanced performance metrics to track
PERFORMANCE_METRICS = {
    "win_rate": "Percentage of profitable trades",
    "average_return": "Average percentage return per trade",
    "total_trades": "Total number of completed trades",
    "total_pnl": "Total profit/loss in dollars",
    "best_trade": "Highest percentage return",
    "worst_trade": "Lowest percentage return",
    "avg_hold_time": "Average time positions are held",
    "success_by_size": "Win rate by position size (lotto/small/half/full)",
    "success_by_channel": "Performance breakdown by channel",
    "monthly_performance": "Performance breakdown by month",
    "risk_adjusted_returns": "Returns adjusted for risk taken",
    "max_drawdown": "Maximum peak-to-trough decline",
    "sharpe_ratio": "Risk-adjusted return metric",
    "profit_factor": "Ratio of gross profit to gross loss"
}

# Alert formatting configuration
ALERT_CONFIG = {
    "show_timestamps": True,
    "show_user_info": True,
    "show_performance_metrics": True,
    "include_market_context": True,
    "format_currency": True,
    "show_position_sizing": True,
    "show_channel_attribution": True,
    "include_risk_metrics": True
}

# Enhanced logging configuration
LOGGING_CONFIG = {
    "log_level": "DEBUG",
    "max_log_size_mb": 100,
    "backup_count": 5,
    "log_format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "channels_to_log": ["ALL"],  # or specific channel names
    "log_trade_details": True,
    "log_parsing_attempts": True,
    "log_performance_updates": True
}

# Alert system resilience configuration
ALERT_RESILIENCE_CONFIG = {
    "max_retries": 3,
    "retry_delay_seconds": [1, 2, 5],  # Exponential backoff
    "circuit_breaker_threshold": 5,
    "circuit_breaker_timeout": 300,  # 5 minutes
    "watchdog_interval": 30,  # Check every 30 seconds
    "emergency_backup_enabled": True,
    "queue_persistence_enabled": True,
    "health_check_interval": 1800  # 30 minutes
}

# Channel isolation settings
CHANNEL_ISOLATION_CONFIG = {
    "strict_position_isolation": True,
    "channel_specific_feedback": True,
    "cross_channel_fallback": False,  # Set to True only for debugging
    "position_cleanup_days": 30,
    "backup_position_data": True
}

# Risk management configuration
RISK_MANAGEMENT_CONFIG = {
    "max_positions_per_channel": 5,
    "max_total_exposure": 0.25,  # 25% of portfolio
    "position_correlation_check": True,
    "sector_concentration_limit": 0.15,  # 15% in any sector
    "daily_loss_limit": 0.10,  # 10% daily loss limit
    "emergency_exit_threshold": 0.20  # 20% portfolio loss triggers emergency exit
}

# Enhanced order management with SPEED OPTIMIZATIONS
ORDER_MANAGEMENT_CONFIG = {
    "order_timeout_seconds": 600,  # 10 minutes
    "price_improvement_attempts": 3,
    "market_hours_only": False,  # Allow extended hours trading
    "minimum_spread_check": True,
    "liquidity_check_enabled": True,
    "auto_cancel_stale_orders": True,
    
    # CRITICAL SPEED OPTIMIZATIONS
    "robinhood_tick_cache_ttl": 300,  # 5 minutes tick size cache
    "trade_first_alert_last": True,   # Global setting for trade-first workflow
    "async_non_critical_updates": True,  # Fire alerts/tracking async
    "fast_execution_logging": True    # Minimal logging during execution
}

# Symbol normalization configuration
SYMBOL_NORMALIZATION_CONFIG = {
    "enabled": True,
    "log_conversions": True,
    "store_both_symbols": True,  # Store both original and broker symbols
    "search_all_variants": True  # Search using all symbol variants
}