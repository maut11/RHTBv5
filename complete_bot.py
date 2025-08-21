# complete_bot.py - Complete RHTB v4 Trading Bot (All-in-One)
import os
import json
import asyncio
import time
import sqlite3
import csv
import logging
import traceback
import hashlib
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import discord
import aiohttp
from openai import OpenAI
import uuid
from collections import deque
from asyncio import Queue
import threading
from threading import Lock
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path
import statistics

# --- Load Environment & Config ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_USER_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --- Channel IDs and Webhooks ---
LIVE_COMMAND_CHANNEL_ID = 1401792635483717747

PLAYS_WEBHOOK = "https://discord.com/api/webhooks/1397759819590537366/WQu-ryRbotOx0Zyz2zH17ls9TGuxeDIZ4T9I3uOlpfwnCswGZrAs5VfHTwHxNWkqXwFw"
ALL_NOTIFICATION_WEBHOOK = "https://discord.com/api/webhooks/1400001289374662787/QsFEWAMTGkKPXZbJXMBPUCRfD1K8x4-_OrT4iY3WqELCzrBdL1DnROT540RsS_4nk8UQ"
LIVE_FEED_WEBHOOK = "https://discord.com/api/webhooks/1404682958564233226/lFCIL_VhoWpdn88fuCyWD4dQ9duTEi_W-0MzIvSrfETy3f9yj-O1Yxgzk1YHOunHLGP5"
COMMANDS_WEBHOOK = "https://discord.com/api/webhooks/1402044700378267800/C2ooBVpV-lyj1COQM2OUH2u8gjNr0QhODrC0qR1leZJAMCQvnxnqrzE7xHUbIDmL8RQ9"

# --- Import Config and Essential Classes ---
from config import *
from trader import RobinhoodTrader, SimulatedTrader
from position_manager import PositionManager

# Import all channel parsers
from channels.sean import SeanParser
from channels.will import WillParser
from channels.eva import EvaParser
from channels.ryan import RyanParser
from channels.fifi import FiFiParser
from channels.price_parser import PriceParser

# --- Comprehensive Logging System ---
class ComprehensiveLogger:
    """All-in-one logging system"""
    
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # Database for structured logging
        self.db_file = self.log_dir / "debug_analytics.db"
        self.lock = Lock()
        
        # Initialize components
        self._setup_database()
        self._setup_file_logging()
        
        # In-memory caches
        self.recent_parses = []
        self.recent_errors = []
        self.metrics = {
            'session_start': datetime.now(timezone.utc).isoformat(),
            'total_messages_processed': 0,
            'successful_parses': 0,
            'failed_parses': 0,
            'trades_executed': 0,
            'alerts_sent': 0,
            'errors_encountered': 0,
            'channels_active': set(),
            'avg_parse_time': 0.0,
            'avg_trade_time': 0.0
        }
        
        print(f"✅ Comprehensive logging initialized: {self.log_dir}")
    
    def _setup_database(self):
        """Initialize SQLite database"""
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            
            # Parse attempts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS parse_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    channel_name TEXT NOT NULL,
                    message_id TEXT,
                    raw_message TEXT NOT NULL,
                    success BOOLEAN,
                    error_message TEXT,
                    latency_ms REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Trade executions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    channel_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    ticker TEXT,
                    execution_success BOOLEAN,
                    error_details TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
            conn.close()
    
    def _setup_file_logging(self):
        """Setup file-based logging"""
        # Setup Python logging
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        
        # Main debug logger
        self.debug_logger = logging.getLogger('rhtb_debug')
        self.debug_logger.setLevel(logging.DEBUG)
        
        if not self.debug_logger.handlers:
            debug_handler = logging.FileHandler(self.log_dir / "debug.log")
            debug_handler.setFormatter(logging.Formatter(log_format))
            self.debug_logger.addHandler(debug_handler)
        
        # Error logger
        self.error_logger = logging.getLogger('rhtb_errors')
        self.error_logger.setLevel(logging.ERROR)
        
        if not self.error_logger.handlers:
            error_handler = logging.FileHandler(self.log_dir / "errors.log")
            error_handler.setFormatter(logging.Formatter(log_format))
            self.error_logger.addHandler(error_handler)
    
    def log_main(self, message: str, level: int = logging.INFO):
        """Log to main bot logger"""
        self.debug_logger.log(level, message)
    
    def log_error(self, message: str, exception: Exception = None):
        """Log error with full traceback"""
        if exception:
            self.error_logger.error(f"{message} - Exception: {str(exception)}", exc_info=True)
        else:
            self.error_logger.error(message)
        
        self.metrics['errors_encountered'] += 1
    
    def log_parse_attempt(self, channel: str, message: str, success: bool, error: str = None):
        """Log parse attempt"""
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO parse_attempts 
                (timestamp, channel_name, raw_message, success, error_message)
                VALUES (?, ?, ?, ?, ?)
            """, (
                datetime.now(timezone.utc).isoformat(),
                channel, message[:500], success, error
            ))
            
            conn.commit()
            conn.close()
        
        self.metrics['total_messages_processed'] += 1
        if success:
            self.metrics['successful_parses'] += 1
        else:
            self.metrics['failed_parses'] += 1
    
    def log_trade_attempt(self, action: str, details: dict, success: bool, error: str = None):
        """Log trade execution"""
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO trade_executions 
                (timestamp, channel_name, action, ticker, execution_success, error_details)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.now(timezone.utc).isoformat(),
                details.get('channel', 'Unknown'),
                action,
                details.get('ticker', ''),
                success,
                error
            ))
            
            conn.commit()
            conn.close()
        
        if success:
            self.metrics['trades_executed'] += 1

# --- Enhanced Performance Tracker ---
@dataclass
class TradeRecord:
    """Trade record data class"""
    trade_id: str
    channel: str
    ticker: str
    strike: float
    option_type: str
    expiration: str
    entry_time: datetime
    exit_time: Optional[datetime]
    entry_price: float
    exit_price: Optional[float]
    quantity: int
    size_category: str
    pnl_dollars: Optional[float]
    pnl_percent: Optional[float]
    status: str

class EnhancedPerformanceTracker:
    """Enhanced performance tracking system"""
    
    def __init__(self, db_file: str = "performance_tracking.db"):
        self.db_file = db_file
        self.lock = Lock()
        self._initialize_database()
        
        # Setup logging
        self.logger = logging.getLogger('performance_tracker')
        self.logger.setLevel(logging.DEBUG)
        
        if not self.logger.handlers:
            handler = logging.FileHandler("logs/performance_tracker.log")
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
    
    def _initialize_database(self):
        """Initialize the SQLite database"""
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            
            # Enhanced trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT UNIQUE NOT NULL,
                    channel TEXT NOT NULL,
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
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Check for quantity_remaining column and add if missing
            cursor.execute("PRAGMA table_info(trades)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'quantity_remaining' not in columns:
                self.logger.info("Adding quantity_remaining column...")
                cursor.execute("ALTER TABLE trades ADD COLUMN quantity_remaining INTEGER DEFAULT 0")
                # Update existing records
                cursor.execute("UPDATE trades SET quantity_remaining = quantity WHERE status = 'open'")
                conn.commit()
            
            conn.close()
    
    def record_entry(self, trade_data: Dict) -> str:
        """Record a new trade entry"""
        with self.lock:
            trade_id = trade_data.get('trade_id') or f"trade_{datetime.now().timestamp()}"
            
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            
            try:
                quantity = trade_data.get('quantity', 1)
                size_category = trade_data.get('size', 'full')
                
                cursor.execute("""
                    INSERT INTO trades (
                        trade_id, channel, ticker, strike, option_type, expiration,
                        entry_time, entry_price, quantity, quantity_remaining, 
                        size_category, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
                """, (
                    trade_id,
                    trade_data.get('channel', 'Unknown'),
                    trade_data.get('ticker', ''),
                    trade_data.get('strike', 0),
                    trade_data.get('type', ''),
                    trade_data.get('expiration', ''),
                    datetime.now(timezone.utc).isoformat(),
                    trade_data.get('price', 0),
                    quantity,
                    quantity,
                    size_category
                ))
                
                conn.commit()
                self.logger.info(f"Recorded entry for {trade_data.get('ticker')} (ID: {trade_id})")
                
            except sqlite3.IntegrityError:
                self.logger.warning(f"Trade {trade_id} already exists")
            finally:
                conn.close()
            
            return trade_id
    
    def find_open_trade_by_ticker(self, ticker: str, channel: str = None) -> Optional[str]:
        """Find most recent open trade ID by ticker"""
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            
            try:
                if channel:
                    cursor.execute("""
                        SELECT trade_id FROM trades 
                        WHERE ticker = ? AND channel = ? AND status = 'open'
                        ORDER BY entry_time DESC LIMIT 1
                    """, (ticker, channel))
                else:
                    cursor.execute("""
                        SELECT trade_id FROM trades 
                        WHERE ticker = ? AND status = 'open'
                        ORDER BY entry_time DESC LIMIT 1
                    """, (ticker,))
                
                result = cursor.fetchone()
                return result[0] if result else None
                
            except Exception as e:
                self.logger.error(f"Error finding trade by ticker: {e}")
                return None
            finally:
                conn.close()
    
    def record_trim(self, trade_id: str, trim_data: Dict) -> Optional[TradeRecord]:
        """Record a trim action"""
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            try:
                cursor.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,))
                trade_row = cursor.fetchone()
                
                if not trade_row:
                    ticker = trim_data.get('ticker')
                    if ticker:
                        cursor.execute("""
                            SELECT * FROM trades 
                            WHERE ticker = ? AND status = 'open'
                            ORDER BY entry_time DESC LIMIT 1
                        """, (ticker,))
                        trade_row = cursor.fetchone()
                        if trade_row:
                            trade_id = trade_row['trade_id']
                
                if not trade_row:
                    self.logger.error(f"Trade {trade_id} not found for trim")
                    return None
                
                trim_quantity = trim_data.get('quantity', 1)
                current_remaining = trade_row['quantity_remaining']
                new_remaining = max(0, current_remaining - trim_quantity)
                
                cursor.execute("""
                    UPDATE trades SET 
                        quantity_remaining = ?
                    WHERE trade_id = ?
                """, (new_remaining, trade_id))
                
                conn.commit()
                self.logger.info(f"Recorded trim for {trade_row['ticker']}: {trim_quantity} contracts")
                
                return TradeRecord(
                    trade_id=trade_id,
                    channel=trade_row['channel'],
                    ticker=trade_row['ticker'],
                    strike=trade_row['strike'],
                    option_type=trade_row['option_type'],
                    expiration=trade_row['expiration'],
                    entry_time=datetime.fromisoformat(trade_row['entry_time'].replace('Z', '+00:00')),
                    exit_time=None,
                    entry_price=trade_row['entry_price'],
                    exit_price=trim_data.get('price', 0),
                    quantity=trade_row['quantity'],
                    size_category=trade_row['size_category'],
                    pnl_dollars=0,
                    pnl_percent=0,
                    status='partially_closed'
                )
                
            except Exception as e:
                self.logger.error(f"Error recording trim: {e}")
                return None
            finally:
                conn.close()
    
    def record_exit(self, trade_id: str, exit_data: Dict) -> Optional[TradeRecord]:
        """Record a complete exit"""
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            try:
                cursor.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,))
                trade_row = cursor.fetchone()
                
                if not trade_row:
                    ticker = exit_data.get('ticker')
                    if ticker:
                        cursor.execute("""
                            SELECT * FROM trades 
                            WHERE ticker = ? AND status = 'open'
                            ORDER BY entry_time DESC LIMIT 1
                        """, (ticker,))
                        trade_row = cursor.fetchone()
                        if trade_row:
                            trade_id = trade_row['trade_id']
                
                if not trade_row:
                    self.logger.error(f"Trade {trade_id} not found for exit")
                    return None
                
                entry_time = datetime.fromisoformat(trade_row['entry_time'].replace('Z', '+00:00'))
                exit_time = datetime.now(timezone.utc)
                exit_price = exit_data.get('price', 0)
                entry_price = trade_row['entry_price']
                
                # Calculate P&L
                if exit_price > 0 and entry_price > 0:
                    pnl_percent = ((exit_price - entry_price) / entry_price) * 100
                    pnl_dollars = (exit_price - entry_price) * trade_row['quantity'] * 100
                else:
                    pnl_percent = 0
                    pnl_dollars = 0
                
                cursor.execute("""
                    UPDATE trades SET 
                        exit_time = ?,
                        exit_price = ?,
                        quantity_remaining = 0,
                        pnl_dollars = ?,
                        pnl_percent = ?,
                        status = 'closed'
                    WHERE trade_id = ?
                """, (
                    exit_time.isoformat(),
                    exit_price,
                    pnl_dollars,
                    pnl_percent,
                    trade_id
                ))
                
                conn.commit()
                
                trade_record = TradeRecord(
                    trade_id=trade_id,
                    channel=trade_row['channel'],
                    ticker=trade_row['ticker'],
                    strike=trade_row['strike'],
                    option_type=trade_row['option_type'],
                    expiration=trade_row['expiration'],
                    entry_time=entry_time,
                    exit_time=exit_time,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    quantity=trade_row['quantity'],
                    size_category=trade_row['size_category'],
                    pnl_dollars=pnl_dollars,
                    pnl_percent=pnl_percent,
                    status='closed'
                )
                
                self.logger.info(f"Recorded exit for {trade_row['ticker']}: {pnl_percent:+.2f}%")
                
                return trade_record
                
            except Exception as e:
                self.logger.error(f"Error recording exit: {e}")
                return None
            finally:
                conn.close()
    
    def get_recent_trades(self, limit: int = 10) -> List[Dict]:
        """Get most recent completed trades"""
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    SELECT * FROM trades 
                    WHERE status = 'closed' 
                    ORDER BY exit_time DESC 
                    LIMIT ?
                """, (limit,))
                
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
                    
            finally:
                conn.close()
        
        return []

# --- Enhanced Alert System ---
class EnhancedAlertSystem:
    """Professional alert formatting system"""
    
    COLORS = {
        'buy': 0x00C851,
        'sell': 0xFF4444,
        'trim': 0xFF8800,
        'exit': 0xFF4444,
        'error': 0xFF0000,
        'info': 0x2196F3,
        'success': 0x4CAF50
    }
    
    EMOJIS = {
        'buy': '🟢',
        'sell': '🔴', 
        'trim': '🟡',
        'exit': '🔴',
        'error': '❌',
        'success': '✅',
        'info': 'ℹ️',
        'money': '💰',
        'chart': '📈'
    }
    
    def __init__(self):
        self.alert_counter = 0
    
    def format_currency(self, amount: float) -> str:
        """Format currency with proper symbols"""
        if abs(amount) >= 1000:
            return f"${amount:,.2f}"
        else:
            return f"${amount:.2f}"
    
    def create_trade_alert(self, trade_data: Dict, action: str, quantity: int, 
                          price: float, is_simulation: bool = True) -> Dict:
        """Create a comprehensive trade alert embed"""
        self.alert_counter += 1
        
        embed = {
            "title": self._create_alert_title(trade_data, action, is_simulation),
            "color": self.COLORS.get(action, self.COLORS['info']),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fields": [],
            "footer": {
                "text": f"RHTB v4 • Alert #{self.alert_counter}"
            }
        }
        
        # Contract details
        contract_info = self._format_contract_details(trade_data)
        embed["fields"].append({
            "name": f"{self.EMOJIS['chart']} Contract Details",
            "value": contract_info,
            "inline": True
        })
        
        # Execution details
        execution_info = self._format_execution_details(action, quantity, price)
        embed["fields"].append({
            "name": f"{self.EMOJIS['money']} Execution Details", 
            "value": execution_info,
            "inline": True
        })
        
        if is_simulation:
            embed["author"] = {
                "name": "🧪 SIMULATION MODE"
            }
        
        return embed
    
    def _create_alert_title(self, trade_data: Dict, action: str, is_simulation: bool) -> str:
        """Create alert title"""
        emoji = self.EMOJIS.get(action, '')
        mode = "[SIM]" if is_simulation else "[LIVE]"
        channel = trade_data.get('channel', 'Unknown')
        ticker = trade_data.get('ticker', 'Unknown')
        
        action_text = action.upper()
        
        return f"{emoji} {mode} {channel} • {action_text} • {ticker}"
    
    def _format_contract_details(self, trade_data: Dict) -> str:
        """Format contract details"""
        ticker = trade_data.get('ticker', 'N/A')
        strike = trade_data.get('strike', 0)
        option_type = trade_data.get('type', 'N/A')
        expiration = trade_data.get('expiration', 'N/A')
        
        try:
            exp_date = datetime.fromisoformat(expiration).strftime('%m/%d/%y')
        except:
            exp_date = expiration
        
        type_symbol = option_type[0].upper() if option_type else 'N/A'
        
        return f"**{ticker}** ${strike}{type_symbol} {exp_date}"
    
    def _format_execution_details(self, action: str, quantity: int, price: float) -> str:
        """Format execution details"""
        position_value = price * quantity * 100
        
        details = [
            f"**Quantity:** {quantity} contracts",
            f"**Price:** {self.format_currency(price)}",
            f"**Total Value:** {self.format_currency(position_value)}"
        ]
        
        return "\n".join(details)
    
    def create_error_alert(self, error_message: str, context: Dict = None) -> Dict:
        """Create an error alert"""
        embed = {
            "title": f"{self.EMOJIS['error']} Trading Bot Error",
            "description": f"```{error_message}```",
            "color": self.COLORS['error'],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fields": []
        }
        
        if context:
            context_text = []
            for key, value in context.items():
                context_text.append(f"**{key.title()}:** {value}")
            
            embed["fields"].append({
                "name": f"{self.EMOJIS['info']} Context",
                "value": "\n".join(context_text),
                "inline": False
            })
        
        return embed

# --- Enhanced Alert Queue ---
class RobustAlertQueueManager:
    """Enhanced alert queue with retry logic"""
    
    def __init__(self, log_dir: str = "logs"):
        self.queue = asyncio.Queue()
        self.processing = False
        self.min_delay = 0.5
        self.max_retries = 3
        self.task = None
        
        # Setup logging
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        self.logger = logging.getLogger('alert_queue')
        self.logger.setLevel(logging.DEBUG)
        
        if not self.logger.handlers:
            file_handler = logging.FileHandler(self.log_dir / "alert_queue.log")
            file_handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
            self.logger.addHandler(file_handler)
        
        # Metrics
        self.metrics = {
            'total_alerts': 0,
            'successful_alerts': 0,
            'failed_alerts': 0,
            'session_start': datetime.now(timezone.utc).isoformat()
        }
        
        self.logger.info("Enhanced Alert Queue Manager initialized")
        
    async def add_alert(self, webhook_url: str, payload: Dict, alert_type: str = "general", priority: int = 0):
        """Add alert to queue"""
        alert_item = {
            'id': f"alert_{int(time.time() * 1000)}_{self.metrics['total_alerts']}",
            'webhook_url': webhook_url,
            'payload': payload,
            'alert_type': alert_type,
            'priority': priority,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'retry_count': 0,
            'max_retries': self.max_retries
        }
        
        await self.queue.put(alert_item)
        self.metrics['total_alerts'] += 1
        
        self.logger.info(f"Alert added: {alert_type} (Queue: {self.queue.qsize()})")
        
    async def process_alerts(self):
        """Process alerts with retry logic"""
        self.processing = True
        self.logger.info("Alert processor started")
        
        while self.processing:
            try:
                alert_item = await asyncio.wait_for(
                    self.queue.get(), timeout=1.0
                )
                
                success = await self._send_alert_with_retry(alert_item)
                
                if success:
                    self.metrics['successful_alerts'] += 1
                    self.logger.info(f"Alert sent successfully: {alert_item['id']}")
                else:
                    self.metrics['failed_alerts'] += 1
                    self.logger.error(f"Alert failed permanently: {alert_item['id']}")
                
                await asyncio.sleep(self.min_delay)
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.logger.error(f"Critical error in alert processor: {e}")
                await asyncio.sleep(self.min_delay)
    
    async def _send_alert_with_retry(self, alert_item: Dict) -> bool:
        """Send alert with retry logic"""
        webhook_url = alert_item['webhook_url']
        payload = alert_item['payload']
        alert_id = alert_item['id']
        
        for attempt in range(alert_item['max_retries'] + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    if 'username' not in payload:
                        payload['username'] = "RHTB v4"
                    
                    timeout = aiohttp.ClientTimeout(total=30)
                    
                    async with session.post(webhook_url, json=payload, timeout=timeout) as resp:
                        if resp.status in (200, 204):
                            if attempt > 0:
                                self.logger.info(f"Alert {alert_id} succeeded on retry {attempt}")
                            return True
                        else:
                            error_text = await resp.text()
                            self.logger.warning(f"Alert {alert_id} attempt {attempt + 1} failed: {resp.status}")
                            
                            if attempt == alert_item['max_retries']:
                                self.logger.error(f"Alert {alert_id} failed permanently")
                                return False
                            
            except asyncio.TimeoutError:
                self.logger.warning(f"Alert {alert_id} attempt {attempt + 1} timed out")
                if attempt == alert_item['max_retries']:
                    return False
                    
            except Exception as e:
                self.logger.warning(f"Alert {alert_id} attempt {attempt + 1} exception: {e}")
                if attempt == alert_item['max_retries']:
                    return False
            
            if attempt < alert_item['max_retries']:
                delay = min(2 ** attempt, 10)
                await asyncio.sleep(delay)
        
        return False
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get comprehensive queue metrics"""
        return {
            **self.metrics,
            'queue_size_current': self.queue.qsize(),
            'success_rate': (self.metrics['successful_alerts'] / max(1, self.metrics['total_alerts'])) * 100,
            'is_processing': self.processing
        }
    
    def stop(self):
        """Stop processing alerts"""
        self.processing = False
        self.logger.info("Alert processor stopped")

# --- Global State & Initializations ---
SIM_MODE = False  # Always start in LIVE mode
TESTING_MODE = False  # Always start listening to LIVE channels
DEBUG_MODE = True

# Initialize systems
openai_client = OpenAI(api_key=OPENAI_API_KEY)
live_trader = RobinhoodTrader()
sim_trader = SimulatedTrader()
position_manager = PositionManager("tracked_contracts_live.json")
price_parser = PriceParser(openai_client)

# Initialize enhanced systems
comprehensive_logger = ComprehensiveLogger()
performance_tracker = EnhancedPerformanceTracker()
alert_system = EnhancedAlertSystem()
alert_queue = RobustAlertQueueManager()

# --- Message Edit Tracking ---
class MessageEditTracker:
    def __init__(self):
        self.processed_messages = {}
        self.lock = asyncio.Lock()
        
    async def mark_processed(self, message_id: str, action: str, order_id: str = None):
        """Mark a message as processed"""
        async with self.lock:
            self.processed_messages[message_id] = {
                'action': action,
                'order_id': order_id,
                'timestamp': datetime.now(timezone.utc),
                'trade_id': None
            }
    
    async def get_processed_info(self, message_id: str):
        """Get processing info for a message"""
        async with self.lock:
            return self.processed_messages.get(message_id)

edit_tracker = MessageEditTracker()

# --- Utility Functions ---
def round_to_tick(price: float, tick_size: float, round_up: bool = False) -> float:
    """Round to tick size with optional round up"""
    if tick_size is None or tick_size == 0:
        tick_size = 0.05
    
    if round_up:
        import math
        ticks = math.ceil(price / tick_size)
    else:
        ticks = round(price / tick_size)
    
    rounded = ticks * tick_size
    if rounded < tick_size:
        rounded = tick_size
    
    return round(rounded, 2)

def normalize_keys(data: dict) -> dict:
    """Normalize dictionary keys"""
    if not isinstance(data, dict): 
        return data
    
    cleaned_data = {k.lower().replace(' ', '_'): v for k, v in data.items()}
    
    if 'option_type' in cleaned_data: 
        cleaned_data['type'] = cleaned_data.pop('option_type')
    if 'entry_price' in cleaned_data: 
        cleaned_data['price'] = cleaned_data.pop('entry_price')
    
    if 'ticker' in cleaned_data and isinstance(cleaned_data['ticker'], str):
        cleaned_data['ticker'] = cleaned_data['ticker'].replace('$', '').upper()

    
    return cleaned_data

def monitor_order_fill_efficiently(trader, order_id, max_wait_time=600):
    """Monitor order fill with exponential backoff"""
    start_time = time.time()
    check_intervals = [5, 10, 15, 20, 30, 30, 60, 60, 60, 60]
    total_elapsed = 0
    
    for interval in check_intervals:
        if total_elapsed >= max_wait_time:
            break
            
        time.sleep(interval)
        total_elapsed += interval
        
        try:
            order_info = trader.get_option_order_info(order_id)
            
            if order_info and order_info.get('state') == 'filled':
                elapsed_time = time.time() - start_time
                return True, elapsed_time
            elif order_info and order_info.get('state') in ['cancelled', 'rejected', 'failed']:
                elapsed_time = time.time() - start_time
                return False, elapsed_time
                
        except Exception as e:
            comprehensive_logger.log_error(f"Order monitoring error: {e}", e)
            continue
    
    # Cancel order if timeout
    try:
        trader.cancel_option_order(order_id)
        comprehensive_logger.log_main(f"Order {order_id} cancelled due to timeout")
    except:
        pass
    
    elapsed_time = time.time() - start_time
    return False, elapsed_time

def execute_buy_order(trader, trade_obj, config, log_func):
    """Execute buy order with enhanced error handling"""
    try:
        symbol = trade_obj['ticker']
        strike = trade_obj['strike']
        expiration = trade_obj['expiration']
        opt_type = trade_obj['type']
        price = float(trade_obj.get('price', 0))
        size = trade_obj.get('size', 'full')
        
        if price <= 0:
            log_func("❌ Invalid price for buy order")
            return False, "Invalid price"
        
        # Calculate position sizing
        portfolio_value = trader.get_portfolio_value()
        allocation = MAX_PCT_PORTFOLIO * POSITION_SIZE_MULTIPLIERS.get(size, 1.0) * config["multiplier"]
        max_amount = min(allocation * portfolio_value, MAX_DOLLAR_AMOUNT)
        
        # Apply channel-specific padding
        buy_padding = config.get("buy_padding", DEFAULT_BUY_PRICE_PADDING)
        tick_size = trader.get_instrument_tick_size(symbol) or 0.05
        padded_price = round_to_tick(price * (1 + buy_padding), tick_size, round_up=True)
        
        contracts = max(MIN_TRADE_QUANTITY, int(max_amount / (padded_price * 100)))
        
        # Store quantity in trade_obj
        trade_obj['quantity'] = contracts
        trade_obj['price'] = padded_price
        
        log_func(f"📤 Placing buy: {contracts}x {symbol} {strike}{opt_type} @ ${padded_price:.2f}")
        
        # Place order
        buy_response = trader.place_option_buy_order(symbol, strike, expiration, opt_type, contracts, padded_price)
        
        if isinstance(trader, SimulatedTrader):
            return True, f"Simulated buy: {contracts}x {symbol}"
        
        order_id = buy_response.get('id')
        if order_id:
            log_func(f"⏳ Monitoring order {order_id}...")
            filled, fill_time = monitor_order_fill_efficiently(trader, order_id, max_wait_time=600)
            
            if filled:
                log_func(f"✅ Buy order filled in {fill_time:.1f}s")
                return True, f"Buy filled: {contracts}x {symbol} @ ${padded_price:.2f}"
            else:
                log_func("❌ Buy order timed out")
                return False, "Order timeout"
        else:
            log_func(f"❌ Buy order failed: {buy_response}")
            return False, f"Order failed: {buy_response.get('error', 'Unknown error')}"
            
    except Exception as e:
        log_func(f"❌ Buy execution error: {e}")
        return False, str(e)

def execute_sell_order(trader, trade_obj, config, log_func, active_position):
    """Execute sell order with enhanced error handling"""
    try:
        symbol = trade_obj['ticker']
        strike = trade_obj['strike']
        expiration = trade_obj['expiration']
        opt_type = trade_obj['type']
        action = trade_obj.get('action', 'exit')
        
        # Get position quantity
        if isinstance(trader, SimulatedTrader):
            total_quantity = 10
        else:
            all_positions = trader.get_open_option_positions()
            position = trader.find_open_option_position(all_positions, symbol, strike, expiration, opt_type)
            if not position:
                log_func(f"❌ No position found for {symbol}")
                return False, "No position found"
            total_quantity = int(float(position.get('quantity', 0)))
        
        # Determine quantity to sell
        if action == "trim":
            sell_quantity = max(1, total_quantity // 2)
        else:
            sell_quantity = total_quantity
        
        trade_obj['quantity'] = sell_quantity
        
        # Cancel existing orders first
        log_func(f"🚫 Cancelling existing orders for {symbol}...")
        cancelled = trader.cancel_open_option_orders(symbol, strike, expiration, opt_type)
        if cancelled > 0:
            log_func(f"✅ Cancelled {cancelled} existing orders")
        
        # Get market price and apply padding
        sell_padding = config.get("sell_padding", DEFAULT_SELL_PRICE_PADDING)
        
        log_func(f"📊 Getting market price for {symbol} {strike}{opt_type}...")
        market_data = trader.get_option_market_data(symbol, expiration, strike, opt_type)
        
        market_price = None
        if market_data and len(market_data) > 0:
            data = market_data[0]
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            
            if isinstance(data, dict):
                mark_price = data.get('mark_price')
                if mark_price and float(mark_price) > 0:
                    market_price = float(mark_price)
                    log_func(f"📈 Using mark price: ${market_price:.2f}")
                else:
                    bid = float(data.get('bid_price', 0) or 0)
                    ask = float(data.get('ask_price', 0) or 0)
                    if bid > 0 and ask > 0:
                        market_price = (bid + ask) / 2
                        log_func(f"📈 Using bid/ask midpoint: ${market_price:.2f}")
                    elif bid > 0:
                        market_price = bid
                        log_func(f"📈 Using bid price: ${market_price:.2f}")
        
        # Fallback price
        if not market_price or market_price <= 0:
            specified_price = trade_obj.get('price', 0)
            if specified_price and specified_price > 0:
                market_price = specified_price * 0.9
                log_func(f"⚠️ Using discounted specified price: ${market_price:.2f}")
            else:
                market_price = 0.05
                log_func(f"🚨 Using emergency minimum price: ${market_price:.2f}")
        
        # Apply padding and round to tick
        final_price = market_price * (1 - sell_padding)
        tick_size = trader.get_instrument_tick_size(symbol) or 0.05
        final_price = round_to_tick(final_price, tick_size)
        
        trade_obj['price'] = final_price
        
        log_func(f"📤 Placing {action}: {sell_quantity}x {symbol} @ ${final_price:.2f}")
        
        # Place sell order
        sell_response = trader.place_option_sell_order(
            symbol, strike, expiration, opt_type, sell_quantity, 
            limit_price=final_price, sell_padding=sell_padding
        )
        
        if isinstance(trader, SimulatedTrader):
            return True, f"Simulated {action}: {sell_quantity}x {symbol}"
        
        if sell_response and not sell_response.get('error'):
            log_func(f"✅ {action.title()} order placed successfully")
            return True, f"{action.title()}: {sell_quantity}x {symbol} @ ${final_price:.2f}"
        else:
            log_func(f"❌ {action.title()} order failed: {sell_response}")
            return False, f"{action.title()} failed: {sell_response.get('error', 'Unknown error')}"
            
    except Exception as e:
        log_func(f"❌ {action.title()} execution error: {e}")
        return False, str(e)

# --- Enhanced Trade Logic ---
def _blocking_handle_trade(loop, handler, message_meta, raw_msg, is_sim_mode_on, received_ts, message_id=None, is_edit=False):
    start_time = time.time()
    
    def enhanced_log(msg, level="INFO"):
        """Enhanced logging function"""
        if level == "ERROR":
            comprehensive_logger.log_error(msg)
        else:
            comprehensive_logger.log_main(msg)
        
        # Send to Discord via queue
        asyncio.run_coroutine_threadsafe(
            alert_queue.add_alert(ALL_NOTIFICATION_WEBHOOK, {"content": msg}, 
                                f"{level.lower()}_notification"),
            loop
        )
        
        print(msg)

    try:
        enhanced_log(f"🔄 Processing message from {handler.name}: {raw_msg[:100]}...")
        
        # Parse the message
        try:
            parsed_results, latency_ms = handler.parse_message(message_meta, received_ts, enhanced_log)
            comprehensive_logger.log_parse_attempt(handler.name, raw_msg, bool(parsed_results))
            
            if not parsed_results:
                enhanced_log(f"⚠️ No parsed results from {handler.name}")
                return
                
        except Exception as e:
            comprehensive_logger.log_parse_attempt(handler.name, raw_msg, False, str(e))
            enhanced_log(f"❌ Parse error in {handler.name}: {e}", "ERROR")
            return

        for raw_trade_obj in parsed_results:
            try:
                trade_obj = normalize_keys(raw_trade_obj)
                action_value = trade_obj.get("action")
                action = action_value.lower() if action_value else ""
                
                if not action or action == "null": 
                    enhanced_log(f"⏭️ Skipping null action from {handler.name}")
                    continue

                enhanced_log(f"🎯 Processing {action} trade: {trade_obj}")

                # Get config and trader
                config = CHANNELS_CONFIG.get(handler.name)
                if not config:
                    enhanced_log(f"❌ No config found for {handler.name}", "ERROR")
                    continue

                trader = live_trader if not is_sim_mode_on else sim_trader
                
                # Enhanced contract resolution
                trade_obj['channel'] = handler.name
                trade_obj['channel_id'] = handler.channel_id
                
                # Try to find active position for trim/exit actions
                active_position = None
                if action in ("trim", "exit", "stop"):
                    active_position = position_manager.find_position(trade_obj['channel_id'], trade_obj) or {}
                    
                    if not active_position and trade_obj.get('ticker'):
                        trade_id = performance_tracker.find_open_trade_by_ticker(
                            trade_obj['ticker'], handler.name
                        )
                        if trade_id:
                            enhanced_log(f"🔍 Found open trade by ticker: {trade_id}")
                            active_position = {'trade_id': trade_id}

                # Fill in missing contract details
                symbol = trade_obj.get("ticker") or active_position.get("symbol")
                strike = trade_obj.get("strike") or active_position.get("strike")
                expiration = trade_obj.get("expiration") or active_position.get("expiration")
                opt_type = trade_obj.get("type") or active_position.get("type")
                
                trade_obj.update({
                    'ticker': symbol, 
                    'strike': strike, 
                    'expiration': expiration, 
                    'type': opt_type
                })

                if not all([symbol, strike, expiration, opt_type]):
                    enhanced_log(f"❌ Missing contract info: {trade_obj}", "ERROR")
                    continue

                # Execute the trade based on action
                execution_success = False
                result_summary = ""

                if action == "buy":
                    execution_success, result_summary = execute_buy_order(
                        trader, trade_obj, config, enhanced_log
                    )
                    
                    if execution_success:
                        # Generate trade ID and add to trade_obj
                        trade_id = f"trade_{int(datetime.now().timestamp() * 1000)}"
                        trade_obj['trade_id'] = trade_id
                        
                        # Record entry in performance tracker
                        performance_tracker.record_entry(trade_obj)
                        position_manager.add_position(trade_obj['channel_id'], trade_obj)
                        
                        # Send enhanced alert
                        asyncio.run_coroutine_threadsafe(
                            send_enhanced_trade_alert(trade_obj, 'buy', 
                                                    trade_obj.get('quantity', 1), 
                                                    trade_obj.get('price', 0), 
                                                    is_sim_mode_on), 
                            loop
                        )

                elif action in ("trim", "exit", "stop"):
                    # Find the trade ID for performance tracking
                    trade_id = active_position.get('trade_id') if active_position else None
                    if not trade_id and trade_obj.get('ticker'):
                        trade_id = performance_tracker.find_open_trade_by_ticker(
                            trade_obj['ticker'], handler.name
                        )
                    
                    execution_success, result_summary = execute_sell_order(
                        trader, trade_obj, config, enhanced_log, active_position
                    )
                    
                    if execution_success and trade_id:
                        # Record in performance tracker
                        if action == "trim":
                            trade_record = performance_tracker.record_trim(trade_id, {
                                'quantity': trade_obj.get('quantity', 1),
                                'price': trade_obj.get('price', 0),
                                'ticker': trade_obj.get('ticker')
                            })
                        else:  # exit or stop
                            trade_record = performance_tracker.record_exit(trade_id, {
                                'price': trade_obj.get('price', 0),
                                'action': action,
                                'is_stop_loss': action == 'stop',
                                'ticker': trade_obj.get('ticker')
                            })
                            
                            # Clear from position manager on full exit
                            if trade_record:
                                position_manager.clear_position(trade_obj['channel_id'], trade_id)
                        
                        # Send enhanced alert with P&L data
                        if trade_record:
                            asyncio.run_coroutine_threadsafe(
                                send_enhanced_trade_alert(
                                    trade_obj, action, 
                                    trade_obj.get('quantity', 1), 
                                    trade_obj.get('price', 0), 
                                    is_sim_mode_on, trade_record), 
                                loop
                            )

                # Log trade execution
                comprehensive_logger.log_trade_attempt(action, trade_obj, execution_success, 
                                                     result_summary if not execution_success else None)
                enhanced_log(f"📊 Trade Summary: {result_summary}")

            except Exception as trade_error:
                comprehensive_logger.log_error(f"Trade execution error: {trade_error}", trade_error)
                enhanced_log(f"❌ Trade execution failed: {trade_error}", "ERROR")

    except Exception as e:
        comprehensive_logger.log_error(f"Critical error in trade processing: {e}", e)
        enhanced_log(f"❌ Critical trade processing error: {e}", "ERROR")

# --- Enhanced Alert Functions ---
async def send_enhanced_trade_alert(trade_data, action, quantity, price, is_simulation, trade_record=None):
    """Send enhanced trade alert"""
    try:
        # Add P&L data if available
        if trade_record:
            trade_data['entry_price'] = getattr(trade_record, 'entry_price', price)
            trade_data['pnl_dollars'] = getattr(trade_record, 'pnl_dollars', 0)
            trade_data['pnl_percent'] = getattr(trade_record, 'pnl_percent', 0)
        
        alert_embed = alert_system.create_trade_alert(trade_data, action, quantity, price, is_simulation)
        
        # Add to enhanced alert queue
        await alert_queue.add_alert(PLAYS_WEBHOOK, {"embeds": [alert_embed]}, "trade_alert", priority=1)
        
        comprehensive_logger.log_main(f"📨 Trade alert queued: {action} {trade_data.get('ticker', 'Unknown')}")
        
    except Exception as e:
        comprehensive_logger.log_error(f"Error sending trade alert: {e}", e)

async def send_error_alert(error_message, context=None):
    """Send error alert with context"""
    try:
        error_embed = alert_system.create_error_alert(error_message, context)
        await alert_queue.add_alert(ALL_NOTIFICATION_WEBHOOK, {"embeds": [error_embed]}, "error_alert", priority=2)
        comprehensive_logger.log_error(f"Error alert sent: {error_message}")
    except Exception as e:
        comprehensive_logger.log_error(f"Failed to send error alert: {e}", e)

# --- Dynamic Channel Handlers ---
CHANNEL_HANDLERS = {}

def update_channel_handlers():
    """Build channel handlers dynamically"""
    global CHANNEL_HANDLERS
    CHANNEL_HANDLERS.clear()
    
    for name, config in CHANNELS_CONFIG.items():
        parser_class_name = config.get("parser")
        if parser_class_name in globals():
            parser_class = globals()[parser_class_name]
            
            channel_id = config.get("test_id") if TESTING_MODE else config.get("live_id")
            
            if channel_id:
                parser_instance = parser_class(
                    openai_client, channel_id, {**config, "name": name}
                )
                CHANNEL_HANDLERS[channel_id] = parser_instance
    
    mode = "TESTING" if TESTING_MODE else "PRODUCTION"
    comprehensive_logger.log_main(f"✅ Handlers updated for {mode} mode: {list(CHANNEL_HANDLERS.keys())}")

# --- Enhanced Discord Client ---
class EnhancedMyClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.alert_processor_task = None
        self.heartbeat_task_handle = None
        self.start_time = datetime.now(timezone.utc)

    async def heartbeat_task(self):
        """Send periodic heartbeat to confirm bot is alive"""
        while True:
            try:
                await asyncio.sleep(1800)  # Every 30 minutes
                
                uptime = datetime.now(timezone.utc) - self.start_time
                uptime_str = str(uptime).split('.')[0]  # Remove microseconds
                
                # Get current metrics
                queue_metrics = await alert_queue.get_metrics()
                recent_trades = performance_tracker.get_recent_trades(5)
                
                heartbeat_embed = {
                    "title": "💓 RHTB v4 Heartbeat",
                    "description": "Bot is alive and running normally",
                    "color": 0x00ff00,
                    "fields": [
                        {
                            "name": "🕐 System Status",
                            "value": f"""
**Uptime:** {uptime_str}
**Started:** {self.start_time.strftime('%H:%M UTC')}
**Current Time:** {datetime.now(timezone.utc).strftime('%H:%M UTC')}
                            """,
                            "inline": True
                        },
                        {
                            "name": "⚙️ Configuration",
                            "value": f"""
**Simulation:** {'ON' if SIM_MODE else 'OFF'}
**Testing Mode:** {'ON' if TESTING_MODE else 'OFF'}
**Active Channels:** {len(CHANNEL_HANDLERS)}
                            """,
                            "inline": True
                        },
                        {
                            "name": "📊 Activity",
                            "value": f"""
**Alert Queue:** {queue_metrics['queue_size_current']} pending
**Success Rate:** {queue_metrics['success_rate']:.1f}%
**Recent Trades:** {len(recent_trades)}
                            """,
                            "inline": True
                        }
                    ],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "footer": {"text": "Automatic heartbeat every 30 minutes"}
                }
                
                await alert_queue.add_alert(ALL_NOTIFICATION_WEBHOOK, 
                                          {"embeds": [heartbeat_embed]}, 
                                          "heartbeat")
                
                comprehensive_logger.log_main("💓 Heartbeat sent successfully")
                
            except Exception as e:
                comprehensive_logger.log_error(f"Heartbeat error: {e}", e)

    async def on_ready(self):
        comprehensive_logger.log_main(f"✅ Discord client ready: {self.user}")
        
        # Start enhanced alert processor
        if not self.alert_processor_task:
            self.alert_processor_task = asyncio.create_task(alert_queue.process_alerts())
            comprehensive_logger.log_main("✅ Enhanced alert processor started")
        
        # Start heartbeat task
        if not self.heartbeat_task_handle:
            self.heartbeat_task_handle = asyncio.create_task(self.heartbeat_task())
            comprehensive_logger.log_main("💓 Heartbeat task started (30min intervals)")
        
        update_channel_handlers()
        
        # Send startup notification
        startup_embed = {
            "title": "🚀 RHTB v4 Enhanced - System Online",
            "color": 0x00ff00,
            "fields": [
                {
                    "name": "🔧 Configuration",
                    "value": f"""
**Simulation:** {'ON' if SIM_MODE else 'OFF'}
**Testing Mode:** {'ON' if TESTING_MODE else 'OFF'}
**Debug Mode:** {'ON' if DEBUG_MODE else 'OFF'}
**Channels:** {len(CHANNEL_HANDLERS)} active
                    """,
                    "inline": True
                },
                {
                    "name": "📊 Enhanced Features",
                    "value": """
**Comprehensive Logging:** ✅
**Enhanced Performance Tracking:** ✅
**Robust Alert Queue:** ✅
**Heartbeat System:** ✅
**Error Recovery:** ✅
                    """,
                    "inline": True
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        await alert_queue.add_alert(ALL_NOTIFICATION_WEBHOOK, {"embeds": [startup_embed]}, "startup", priority=3)

    async def on_message(self, message):
        """Enhanced message handling"""
        try:
            # Handle commands
            if message.channel.id == LIVE_COMMAND_CHANNEL_ID and message.content.startswith('!'):
                await self.handle_command(message)
                return

            # Handle trading messages
            if message.channel.id in CHANNEL_HANDLERS:
                handler = CHANNEL_HANDLERS[message.channel.id]
                
                comprehensive_logger.log_main(f"📨 Message received from {handler.name}: {message.content[:100]}...")
                
                # Extract message content
                message_meta, raw_msg = self.extract_message_content(message, handler)
                
                if raw_msg:
                    # Log to live feed
                    await self.send_live_feed_alert(handler, raw_msg)
                    
                    # Process trade
                    received_ts = datetime.now(timezone.utc)
                    self.loop.run_in_executor(
                        None, 
                        _blocking_handle_trade, 
                        self.loop, handler, message_meta, raw_msg, 
                        SIM_MODE, received_ts, str(message.id), False
                    )
                    
        except Exception as e:
            comprehensive_logger.log_error(f"Message handling error: {e}", e)

    async def on_message_edit(self, before, after):
        """Enhanced edit handling"""
        try:
            if before.content == after.content and before.embeds == after.embeds:
                return
                
            if after.channel.id in CHANNEL_HANDLERS:
                handler = CHANNEL_HANDLERS[after.channel.id]
                
                comprehensive_logger.log_main(f"📝 Message edit detected in {handler.name}")
                
                processed_info = await edit_tracker.get_processed_info(str(after.id))
                if processed_info:
                    # Handle the edit
                    message_meta, raw_msg = self.extract_message_content(after, handler)
                    
                    if raw_msg:
                        received_ts = datetime.now(timezone.utc)
                        self.loop.run_in_executor(
                            None, 
                            _blocking_handle_trade, 
                            self.loop, handler, message_meta, raw_msg, 
                            SIM_MODE, received_ts, str(after.id), True
                        )
                        
        except Exception as e:
            comprehensive_logger.log_error(f"Edit handling error: {e}", e)

    def extract_message_content(self, message, handler):
        """Extract message content for processing"""
        try:
            current_embed_title = ""
            current_embed_desc = ""
            
            if message.embeds:
                embed = message.embeds[0]
                current_embed_title = embed.title or ""
                current_embed_desc = embed.description or ""
            
            current_content = message.content or ""
            current_full_text = f"Title: {current_embed_title}\nDesc: {current_embed_desc}" if current_embed_title else current_content
            
            # Handle replies
            original_full_text = None
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
                
                message_meta = (current_full_text, original_full_text)
                raw_msg = f"Reply: '{current_full_text}'\nOriginal: '{original_full_text}'"
            else:
                message_meta = (current_embed_title, current_embed_desc) if current_embed_title else current_content
                raw_msg = current_full_text
            
            return message_meta, raw_msg
            
        except Exception as e:
            comprehensive_logger.log_error(f"Content extraction error: {e}", e)
            return None, ""

    async def send_live_feed_alert(self, handler, content):
        """Send message to live feed"""
        try:
            live_feed_embed = {
                "author": {"name": f"{handler.name}'s Channel"},
                "description": content[:2000],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "color": handler.color,
                "footer": {"text": "TESTING MODE" if TESTING_MODE else "PRODUCTION"}
            }
            await alert_queue.add_alert(LIVE_FEED_WEBHOOK, {"embeds": [live_feed_embed]}, "live_feed")
            
        except Exception as e:
            comprehensive_logger.log_error(f"Live feed alert error: {e}", e)

    async def handle_command(self, message):
        """Enhanced command handling"""
        try:
            content = message.content
            parts = content.split()
            command = parts[0].lower()
            
            comprehensive_logger.log_main(f"🎮 Command received: {command}")
            
            # Handle global mode changes
            global SIM_MODE, TESTING_MODE, DEBUG_MODE
            
            if command == "!sim":
                if len(parts) > 1 and parts[1] in ["on", "true"]:
                    SIM_MODE = True
                    response = "✅ **Simulation Mode is now ON.** Orders will be simulated."
                elif len(parts) > 1 and parts[1] in ["off", "false"]:
                    SIM_MODE = False
                    response = "🚨 **Simulation Mode is now OFF.** Orders will be sent to live broker."
                else:
                    response = "Usage: `!sim on` or `!sim off`"
                
                await alert_queue.add_alert(COMMANDS_WEBHOOK, {"content": response}, "command_response")
            
            elif command == "!testing":
                if len(parts) > 1 and parts[1] in ["on", "true"]:
                    TESTING_MODE = True
                    response = "✅ **Testing Mode is now ON.** Listening to SIMULATED channels."
                elif len(parts) > 1 and parts[1] in ["off", "false"]:
                    TESTING_MODE = False
                    response = "🚨 **Testing Mode is now OFF.** Listening to LIVE channels."
                else:
                    response = "Usage: `!testing on` or `!testing off`"
                
                await alert_queue.add_alert(COMMANDS_WEBHOOK, {"content": response}, "command_response")
                await asyncio.sleep(1)
                update_channel_handlers()
            
            # Enhanced status command
            elif command == "!status":
                # Get queue metrics
                queue_metrics = await alert_queue.get_metrics()
                
                status_embed = {
                    "title": "📊 RHTB v4 Enhanced Status",
                    "color": 0x00ff00,
                    "fields": [
                        {
                            "name": "🔧 Configuration",
                            "value": f"""
**Simulation:** {'ON' if SIM_MODE else 'OFF'}
**Testing:** {'ON' if TESTING_MODE else 'OFF'}
**Debug:** {'ON' if DEBUG_MODE else 'OFF'}
**Channels:** {len(CHANNEL_HANDLERS)}
                            """,
                            "inline": True
                        },
                        {
                            "name": "📨 Alert Queue",
                            "value": f"""
**Total Alerts:** {queue_metrics['total_alerts']}
**Success Rate:** {queue_metrics['success_rate']:.1f}%
**Queue Size:** {queue_metrics['queue_size_current']}
                            """,
                            "inline": True
                        },
                        {
                            "name": "📁 Logging",
                            "value": f"""
**All Output:** logs/debug.log
**Errors:** logs/errors.log
**Database:** logs/debug_analytics.db
                            """,
                            "inline": False
                        }
                    ],
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                
                await alert_queue.add_alert(COMMANDS_WEBHOOK, {"embeds": [status_embed]}, "command_response")
            
            # Queue health command
            elif command == "!queue":
                metrics = await alert_queue.get_metrics()
                
                queue_embed = {
                    "title": "📊 Alert Queue Status",
                    "color": 0x00ff00 if metrics['success_rate'] > 90 else 0xff8800,
                    "fields": [
                        {
                            "name": "📈 Metrics",
                            "value": f"""
**Total Processed:** {metrics['total_alerts']}
**Success Rate:** {metrics['success_rate']:.1f}%
**Current Queue:** {metrics['queue_size_current']}
**Processing:** {'Yes' if metrics['is_processing'] else 'No'}
                            """,
                            "inline": True
                        }
                    ]
                }
                
                await alert_queue.add_alert(COMMANDS_WEBHOOK, {"embeds": [queue_embed]}, "command_response")
            
            # Performance tracking command
            elif command == "!trades":
                recent_trades = performance_tracker.get_recent_trades(10)
                
                if recent_trades:
                    trades_text = ""
                    for trade in recent_trades[:5]:
                        pnl_emoji = "🟢" if trade.get('pnl_percent', 0) > 0 else "🔴"
                        trades_text += f"{pnl_emoji} {trade['ticker']}: {trade.get('pnl_percent', 0):+.1f}%\n"
                    
                    trades_embed = {
                        "title": "📊 Recent Trades",
                        "description": trades_text,
                        "color": 0x00ff00,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                else:
                    trades_embed = {
                        "title": "📊 Recent Trades",
                        "description": "No completed trades found",
                        "color": 0x888888
                    }
                
                await alert_queue.add_alert(COMMANDS_WEBHOOK, {"embeds": [trades_embed]}, "command_response")
            
            # Price lookup command
            elif command == "!getprice":
                query = content[len("!getprice"):].strip()
                if not query:
                    await alert_queue.add_alert(COMMANDS_WEBHOOK, {
                        "content": "Usage: `!getprice <options contract query>`\nExample: `!getprice $SPY 500c this friday`"
                    }, "command_response")
                    return
                await self._handle_get_price(query)
                return
            
            # Heartbeat command
            elif command == "!heartbeat":
                uptime = datetime.now(timezone.utc) - self.start_time
                uptime_str = str(uptime).split('.')[0]  # Remove microseconds
                
                # Get detailed system metrics
                queue_metrics = await alert_queue.get_metrics()
                recent_trades = performance_tracker.get_recent_trades(5)
                
                # Get memory/system info if possible
                try:
                    import psutil
                    process = psutil.Process()
                    memory_mb = process.memory_info().rss / 1024 / 1024
                    cpu_percent = process.cpu_percent()
                    system_info = f"**Memory:** {memory_mb:.1f} MB\n**CPU:** {cpu_percent:.1f}%"
                except:
                    system_info = "**System info:** Not available"
                
                heartbeat_embed = {
                    "title": "💓 RHTB v4 Manual Heartbeat",
                    "description": "Detailed bot health status",
                    "color": 0x00ff00,
                    "fields": [
                        {
                            "name": "🕐 Uptime & Timing",
                            "value": f"""
**Current Uptime:** {uptime_str}
**Started At:** {self.start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}
**Current Time:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
**Last Heartbeat:** {'Active' if self.heartbeat_task_handle and not self.heartbeat_task_handle.done() else 'Inactive'}
                            """,
                            "inline": False
                        },
                        {
                            "name": "⚙️ Configuration Status",
                            "value": f"""
**Simulation Mode:** {'🟢 ON' if SIM_MODE else '🔴 OFF (LIVE TRADING)'}
**Testing Mode:** {'🟡 ON (Test Channels)' if TESTING_MODE else '🟢 OFF (Live Channels)'}
**Debug Mode:** {'🟢 ON' if DEBUG_MODE else '🔴 OFF'}
**Active Channels:** {len(CHANNEL_HANDLERS)}
                            """,
                            "inline": True
                        },
                        {
                            "name": "📊 Performance Metrics",
                            "value": f"""
**Alert Queue Size:** {queue_metrics['queue_size_current']}
**Total Alerts Sent:** {queue_metrics['total_alerts']}
**Alert Success Rate:** {queue_metrics['success_rate']:.1f}%
**Recent Trades:** {len(recent_trades)} completed
**Processing Status:** {'🟢 Active' if queue_metrics['is_processing'] else '🔴 Stopped'}
                            """,
                            "inline": True
                        },
                        {
                            "name": "🖥️ System Resources",
                            "value": system_info,
                            "inline": False
                        },
                        {
                            "name": "📝 Recent Activity",
                            "value": f"""
**Logging:** {comprehensive_logger.metrics['total_messages_processed']} messages processed
**Parse Success:** {comprehensive_logger.metrics['successful_parses']}/{comprehensive_logger.metrics['total_messages_processed']} 
**Errors:** {comprehensive_logger.metrics['errors_encountered']} total
**Active Since:** {comprehensive_logger.metrics['session_start'][:16]}
                            """ if hasattr(comprehensive_logger, 'metrics') else "**Logging:** Active\n**Status:** All systems operational",
                            "inline": False
                        }
                    ],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "footer": {"text": f"Manual heartbeat requested • Next auto heartbeat in ~{30 - (uptime.total_seconds() % 1800) // 60:.0f} min"}
                }
                
                # Add recent trades info if available
                if recent_trades:
                    trades_text = ""
                    for trade in recent_trades[:3]:
                        pnl_emoji = "🟢" if trade.get('pnl_percent', 0) > 0 else "🔴"
                        pnl = trade.get('pnl_percent', 0)
                        trades_text += f"{pnl_emoji} {trade['ticker']}: {pnl:+.1f}%\n"
                    
                    heartbeat_embed["fields"].append({
                        "name": "💹 Recent Trades",
                        "value": trades_text,
                        "inline": True
                    })
                
                await alert_queue.add_alert(COMMANDS_WEBHOOK, {"embeds": [heartbeat_embed]}, "manual_heartbeat")
                comprehensive_logger.log_main("💓 Manual heartbeat command executed")
            
            # Help command
            elif command == "!help":
                help_embed = {
                    "title": "🛠️ RHTB v4 Enhanced Commands",
                    "description": """
**Status & Monitoring:**
`!status` - System status and metrics
`!heartbeat` - Detailed health check & uptime
`!queue` - Alert queue health
`!trades` - Recent trade performance

**Trading Controls:**
`!sim on|off` - Toggle simulation mode
`!testing on|off` - Toggle testing channels

**Utilities:**
`!getprice <query>` - Get option market price
`!positions` - Show current positions
`!portfolio` - Show portfolio value

**Enhanced Features:**
• 💓 Automatic heartbeat every 30 minutes
• 📊 Comprehensive file logging
• 🔄 Enhanced performance tracking
• 📡 Robust alert queue with retries
• 🛡️ Automatic error recovery
                    """,
                    "color": 0x3498db
                }
                await alert_queue.add_alert(COMMANDS_WEBHOOK, {"embeds": [help_embed]}, "command_response")
            
            # Portfolio commands
            elif command == "!positions":
                await alert_queue.add_alert(COMMANDS_WEBHOOK, {"content": "⏳ Fetching live account positions..."}, "command_response")
                pos_string = await self.get_positions_string()
                await alert_queue.add_alert(COMMANDS_WEBHOOK, {"content": f"**Current Positions:**\n```\n{pos_string}\n```"}, "command_response")

            elif command == "!portfolio":
                await alert_queue.add_alert(COMMANDS_WEBHOOK, {"content": "⏳ Fetching live account portfolio value..."}, "command_response")
                portfolio_value = await self.loop.run_in_executor(None, live_trader.get_portfolio_value)
                await alert_queue.add_alert(COMMANDS_WEBHOOK, {"content": f"💰 **Total Portfolio Value:** ${portfolio_value:,.2f}"}, "command_response")
            
            else:
                await alert_queue.add_alert(COMMANDS_WEBHOOK, {
                    "content": f"Unknown command: {command}. Use `!help` for available commands."
                }, "command_response")
                
        except Exception as e:
            comprehensive_logger.log_error(f"Command handling error: {e}", e)
            await alert_queue.add_alert(COMMANDS_WEBHOOK, {
                "content": f"❌ Command error: {str(e)}"
            }, "error_response")

    async def get_positions_string(self) -> str:
        """Get current positions as string"""
        try:
            positions = await self.loop.run_in_executor(None, live_trader.get_open_option_positions)
            if not positions:
                return "No open option positions."
            
            holdings = []
            for p in positions:
                try:
                    instrument_data = await self.loop.run_in_executor(None, live_trader.get_option_instrument_data, p['option'])
                    if instrument_data:
                        holdings.append(f"• {p['chain_symbol']} {instrument_data['expiration_date']} {instrument_data['strike_price']}{instrument_data['type'].upper()[0]} x{int(float(p['quantity']))}")
                except Exception as e:
                    print(f"Could not process a position: {e}")
            
            return "\n".join(holdings) if holdings else "No processable option positions found."
        except Exception as e:
            return f"Error retrieving holdings: {e}"

    async def _handle_get_price(self, query: str):
        """Handle the !getprice command"""
        await alert_queue.add_alert(COMMANDS_WEBHOOK, {"content": f"⏳ Parsing and fetching price for: `{query}`..."}, "command_response")

        def blocking_parse_and_fetch():
            """Runs blocking IO calls in a separate thread"""
            def parser_logger(msg, level="INFO"):
                print(f"[{level}] PriceParser: {msg}")

            # Parse the user's query
            parsed_contract = price_parser.parse_query(query, parser_logger)

            if not parsed_contract:
                return {"error": "Could not understand the contract details. Please be more specific (e.g., `$SPY 500c this friday`)."}

            ticker = parsed_contract.get('ticker')
            strike = parsed_contract.get('strike')
            opt_type = parsed_contract.get('type')
            expiration = parsed_contract.get('expiration')

            if not all([ticker, strike, opt_type, expiration]):
                missing = [k for k, v in {'ticker': ticker, 'strike': strike, 'type': opt_type, 'expiration': expiration}.items() if not v]
                return {"error": f"Parsing failed. I'm missing these details: `{', '.join(missing)}`"}

            # Fetch market data
            trader = live_trader if not SIM_MODE else sim_trader
            market_data = trader.get_option_market_data(ticker, expiration, strike, opt_type)
            
            # Handle market data response
            market_data_dict = None
            if market_data and isinstance(market_data, list):
                if market_data[0] and isinstance(market_data[0], list):
                    if len(market_data[0]) > 0 and market_data[0][0] and isinstance(market_data[0][0], dict):
                        market_data_dict = market_data[0][0]
                elif market_data[0] and isinstance(market_data[0], dict):
                    market_data_dict = market_data[0]

            if not market_data_dict:
                return {
                    "error": f"Could not find market data for `{ticker.upper()} ${strike} {opt_type.upper()} {expiration}`. Please check the ticker, strike, and date."
                }
            
            return {"success": True, "data": market_data_dict, "parsed": parsed_contract}

        # Run the blocking function
        result = await self.loop.run_in_executor(None, blocking_parse_and_fetch)

        # Format and send response
        if "error" in result:
            await alert_queue.add_alert(COMMANDS_WEBHOOK, {"content": f"❌ {result['error']}"}, "command_response")
        else:
            data = result['data']
            parsed = result['parsed']
            
            # Extract data points
            bid = float(data.get('bid_price', 0) or 0)
            ask = float(data.get('ask_price', 0) or 0)
            mark = float(data.get('mark_price', 0) or 0)
            volume = int(data.get('volume', 0) or 0)
            open_interest = int(data.get('open_interest', 0) or 0)
            
            # Create response embed
            price_embed = {
                "title": f"📊 Market Price for {parsed.get('ticker').upper()} ${parsed.get('strike')} {parsed.get('type').upper()}",
                "description": f"**Expiration:** {parsed.get('expiration')}",
                "color": 15105642,
                "fields": [
                    {"name": "Mark Price", "value": f"${mark:.2f}", "inline": True},
                    {"name": "Bid Price", "value": f"${bid:.2f}", "inline": True},
                    {"name": "Ask Price", "value": f"${ask:.2f}", "inline": True},
                    {"name": "Bid/Ask Spread", "value": f"${(ask - bid):.2f}", "inline": True},
                    {"name": "Volume", "value": f"{volume:,}", "inline": True},
                    {"name": "Open Interest", "value": f"{open_interest:,}", "inline": True}
                ],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": {"text": f"RHTB v4 • Query: '{query}'"}
            }
            await alert_queue.add_alert(COMMANDS_WEBHOOK, {"embeds": [price_embed]}, "command_response")

    async def on_disconnect(self):
        """Clean shutdown"""
        comprehensive_logger.log_main("🔌 Discord client disconnecting...")
        
        # Stop heartbeat task
        if self.heartbeat_task_handle:
            self.heartbeat_task_handle.cancel()
            comprehensive_logger.log_main("💓 Heartbeat task stopped")
        
        # Stop alert processor
        if self.alert_processor_task:
            alert_queue.stop()
            try:
                await asyncio.wait_for(self.alert_processor_task, timeout=5.0)
            except asyncio.TimeoutError:
                comprehensive_logger.log_main("⏰ Alert processor shutdown timeout")

# --- Main Entry Point ---
if __name__ == "__main__":
    try:
        comprehensive_logger.log_main("🚀 Starting RHTB v4 Enhanced...")
        
        print("📊 Enhanced Features Active:")
        print("   ✅ Comprehensive logging to files")
        print("   ✅ Enhanced performance tracking with trim/exit sequences")
        print("   ✅ Robust alert queue with retry logic")
        print("   ✅ Better error handling and recovery")
        print("   ✅ File-based logging for all Python output")
        print("   ✅ All-in-one consolidated bot")
        print("")
        
        # Log all settings
        comprehensive_logger.log_main(f"Settings: SIM_MODE={SIM_MODE}, TESTING_MODE={TESTING_MODE}, DEBUG_MODE={DEBUG_MODE}")
        
        # Create and run client
        client = EnhancedMyClient()
        client.run(DISCORD_TOKEN)
        
    except Exception as e:
        comprehensive_logger.log_error(f"Critical startup error: {e}", e)
        print(f"❌ Critical error during startup: {e}")
        raise