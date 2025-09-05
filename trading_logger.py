"""
Enhanced logging configuration to reduce noise and improve readability for trading system
"""

import logging
import logging.handlers
from datetime import datetime
from pathlib import Path
import json

class TradingSystemLogger:
    """Enhanced logger with filtering and better formatting"""
    
    def __init__(self, log_level=logging.INFO):
        self.setup_loggers(log_level)
        
    def setup_loggers(self, log_level):
        """Setup structured logging with separate channels"""
        
        # Create logs directory if it doesn't exist
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        
        # 1. Main trading logger (filtered, less noise)
        self.main_logger = logging.getLogger("trading_main")
        self.main_logger.setLevel(log_level)
        
        # Clear any existing handlers
        self.main_logger.handlers.clear()
        
        # Main log formatter (cleaner format)
        main_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Main log file handler (with rotation)
        main_handler = logging.handlers.RotatingFileHandler(
            logs_dir / "trading_main.log",
            maxBytes=50*1024*1024,  # 50MB
            backupCount=5
        )
        main_handler.setFormatter(main_formatter)
        main_handler.addFilter(self._main_log_filter)
        
        # Console handler for main logger (even more filtered)
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        console_handler.addFilter(self._console_filter)
        
        self.main_logger.addHandler(main_handler)
        self.main_logger.addHandler(console_handler)
        
        # 2. Critical events logger (only important events)
        self.critical_logger = logging.getLogger("trading_critical")
        self.critical_logger.setLevel(logging.WARNING)
        
        critical_handler = logging.handlers.RotatingFileHandler(
            logs_dir / "critical_events.log",
            maxBytes=10*1024*1024,  # 10MB
            backupCount=3
        )
        critical_formatter = logging.Formatter(
            '%(asctime)s - CRITICAL - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        critical_handler.setFormatter(critical_formatter)
        self.critical_logger.addHandler(critical_handler)
        
        # 3. Debug logger (full verbosity when needed)
        self.debug_logger = logging.getLogger("trading_debug")
        self.debug_logger.setLevel(logging.DEBUG)
        
        debug_handler = logging.handlers.RotatingFileHandler(
            logs_dir / "debug_full.log",
            maxBytes=100*1024*1024,  # 100MB
            backupCount=2
        )
        debug_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        debug_handler.setFormatter(debug_formatter)
        self.debug_logger.addHandler(debug_handler)
        
        # 4. Suppress noisy third-party loggers
        self._suppress_noisy_loggers()
    
    def _main_log_filter(self, record):
        """Filter out noise from main log"""
        message = record.getMessage().lower()
        
        # Filter out alert manager spam
        if any(phrase in message for phrase in [
            'primary alert manager',
            'backup alert manager',
            'alert queue processing',
            'urllib3.connectionpool',
            'http/1.1'
        ]):
            return False
            
        # Filter out duplicate connection messages
        if 'connection pool' in message:
            return False
            
        # Keep important messages
        if any(phrase in message for phrase in [
            'order placed',
            'order failed',
            'tick size error',
            'trim',
            'buy',
            'sell',
            'error',
            'failed'
        ]):
            return True
            
        # Filter based on log level
        return record.levelno >= logging.INFO
    
    def _console_filter(self, record):
        """Even more aggressive filtering for console output"""
        message = record.getMessage().lower()
        
        # Only show critical trading events on console
        if any(phrase in message for phrase in [
            'order placed',
            'order failed', 
            'tick size error',
            'sell order successful',
            'buy order successful',
            'trim',
            'exit'
        ]):
            return True
            
        # Show warnings and errors
        if record.levelno >= logging.WARNING:
            return True
            
        return False
        
    def _suppress_noisy_loggers(self):
        """Suppress or reduce verbosity of noisy third-party loggers"""
        
        # Suppress HTTP connection pool messages
        logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        
        # Suppress Discord library noise
        logging.getLogger("discord").setLevel(logging.WARNING)
        
        # Suppress requests library
        logging.getLogger("requests").setLevel(logging.WARNING)
        
        # Suppress openai library debug
        logging.getLogger("openai").setLevel(logging.WARNING)
        
    def log_trading_event(self, event_type, message, data=None):
        """Log structured trading events"""
        
        structured_message = f"[{event_type.upper()}] {message}"
        
        if data:
            structured_message += f" | Data: {json.dumps(data, default=str)}"
            
        # Route to appropriate logger
        if event_type in ['ORDER_FAILED', 'TICK_ERROR', 'CONNECTION_ERROR']:
            self.critical_logger.error(structured_message)
            
        self.main_logger.info(structured_message)
        
        # Always log to debug for full history
        self.debug_logger.info(structured_message)
    
    def log_order_event(self, action, symbol, status, details=None):
        """Specialized logging for order events"""
        
        event_data = {
            'action': action,
            'symbol': symbol,
            'status': status,
            'timestamp': datetime.now().isoformat()
        }
        
        if details:
            event_data.update(details)
            
        if status == 'SUCCESS':
            self.log_trading_event('ORDER_SUCCESS', f"{action} {symbol} successful", event_data)
        elif status == 'FAILED':
            self.log_trading_event('ORDER_FAILED', f"{action} {symbol} failed", event_data)
        else:
            self.log_trading_event('ORDER_INFO', f"{action} {symbol} {status}", event_data)
    
    def log_tick_size_event(self, symbol, price, tick_size, source):
        """Log tick size related events"""
        
        event_data = {
            'symbol': symbol,
            'price': price,
            'tick_size': tick_size,
            'source': source
        }
        
        self.log_trading_event('TICK_SIZE', f"Tick size for {symbol}: ${tick_size} (price: ${price}, source: {source})", event_data)

# Global instance
trading_logger = TradingSystemLogger()

def get_trading_logger():
    """Get the main trading logger instance"""
    return trading_logger.main_logger

def get_critical_logger():
    """Get the critical events logger"""
    return trading_logger.critical_logger

def get_debug_logger():
    """Get the debug logger"""
    return trading_logger.debug_logger

def log_order(action, symbol, status, details=None):
    """Convenience function for logging order events"""
    trading_logger.log_order_event(action, symbol, status, details)

def log_tick_size(symbol, price, tick_size, source):
    """Convenience function for logging tick size events"""
    trading_logger.log_tick_size_event(symbol, price, tick_size, source)