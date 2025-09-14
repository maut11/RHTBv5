# performance_tracker.py - Enhanced Performance Tracking with Channel Isolation
import sqlite3
import logging
import os
from datetime import datetime, timezone, timedelta
from threading import Lock
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from contextlib import contextmanager

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
    """
    Enhanced performance tracking system with strict channel isolation.
    Each trade is associated with a specific channel for proper attribution.
    """
    
    def __init__(self, db_file: str = "logs/performance_tracking.db"):
        self.db_file = db_file
        self.lock = Lock()
        self._connection_pool = {}
        
        # Setup logging
        self.logger = logging.getLogger('performance_tracker')
        self.logger.setLevel(logging.DEBUG)
        
        if not self.logger.handlers:
            # Create logs directory if it doesn't exist
            if not os.path.exists('logs'):
                os.makedirs('logs')
            handler = logging.FileHandler("logs/performance_tracker.log")
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        
        # Initialize database
        self._initialize_database()
        self._verify_database_integrity()
        print("✅ Enhanced Performance Tracker initialized with channel isolation")
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections with proper error handling"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_file, timeout=30.0)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.row_factory = sqlite3.Row
            yield conn
        except sqlite3.Error as e:
            self.logger.error(f"Database connection error: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()
    
    def _initialize_database(self):
        """Initialize the SQLite database with enhanced schema"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Enable WAL mode for better concurrency
                cursor.execute("PRAGMA journal_mode=WAL")
                
                # Enhanced trades table
                cursor.execute("""
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
                """)
                
                # Check for missing columns and add them if needed
                cursor.execute("PRAGMA table_info(trades)")
                existing_columns = {column[1] for column in cursor.fetchall()}
                
                columns_to_add = [
                    ('channel_id', 'INTEGER'),
                    ('quantity_remaining', 'INTEGER DEFAULT 0'),
                    ('stop_loss_price', 'REAL'),
                    ('trailing_stop_active', 'INTEGER DEFAULT 0'),
                    ('notes', 'TEXT'),
                    ('updated_at', 'TEXT')
                ]
                
                for col_name, col_type in columns_to_add:
                    if col_name not in existing_columns:
                        try:
                            self.logger.info(f"Adding column {col_name} to trades table")
                            cursor.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")
                        except sqlite3.OperationalError as e:
                            if "duplicate column" not in str(e).lower():
                                self.logger.error(f"Error adding column {col_name}: {e}")
                
                # Fix any existing records
                cursor.execute("""
                    UPDATE trades 
                    SET quantity_remaining = quantity 
                    WHERE status = 'open' AND quantity_remaining IS NULL
                """)
                
                cursor.execute("""
                    UPDATE trades 
                    SET updated_at = created_at 
                    WHERE updated_at IS NULL
                """)
                
                # Create indexes for better performance
                indexes = [
                    ("idx_trades_channel", "trades(channel)"),
                    ("idx_trades_ticker", "trades(ticker)"),
                    ("idx_trades_status", "trades(status)"),
                    ("idx_trades_channel_ticker", "trades(channel, ticker)"),
                    ("idx_trades_trade_id", "trades(trade_id)"),
                    ("idx_trades_entry_time", "trades(entry_time)")
                ]
                
                for index_name, index_def in indexes:
                    cursor.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {index_def}")
                
                # Trade events table for detailed tracking
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trade_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trade_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        event_time TEXT NOT NULL,
                        quantity INTEGER,
                        price REAL,
                        notes TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_trade_id ON trade_events(trade_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_time ON trade_events(event_time)")
                
                # Performance summary table for quick stats
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS performance_summary (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        channel TEXT NOT NULL,
                        date TEXT NOT NULL,
                        total_trades INTEGER DEFAULT 0,
                        winning_trades INTEGER DEFAULT 0,
                        losing_trades INTEGER DEFAULT 0,
                        total_pnl REAL DEFAULT 0,
                        best_trade REAL DEFAULT 0,
                        worst_trade REAL DEFAULT 0,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(channel, date)
                    )
                """)
                
                conn.commit()
                self.logger.info("Database initialized successfully")
                
        except Exception as e:
            self.logger.error(f"Database initialization error: {e}")
            raise
    
    def _verify_database_integrity(self):
        """Verify database integrity and fix issues"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Check for integrity issues
                cursor.execute("PRAGMA integrity_check")
                result = cursor.fetchone()
                if result[0] != "ok":
                    self.logger.warning(f"Database integrity check failed: {result[0]}")
                    # Attempt to recover
                    cursor.execute("VACUUM")
                    conn.commit()
                    self.logger.info("Database vacuumed")
                
                # Check for orphaned trade events
                cursor.execute("""
                    DELETE FROM trade_events 
                    WHERE trade_id NOT IN (SELECT trade_id FROM trades)
                """)
                deleted = cursor.rowcount
                if deleted > 0:
                    self.logger.info(f"Cleaned up {deleted} orphaned trade events")
                    conn.commit()
                    
        except Exception as e:
            self.logger.error(f"Database integrity check error: {e}")
    
    def record_entry(self, trade_data: Dict) -> str:
        """Record a new trade entry with enhanced channel tracking"""
        with self.lock:
            trade_id = trade_data.get('trade_id') or f"trade_{int(datetime.now().timestamp() * 1000)}"
            
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Prepare data
                    quantity = trade_data.get('quantity', 1)
                    size_category = trade_data.get('size', 'full')
                    channel = trade_data.get('channel', 'Unknown')
                    channel_id = trade_data.get('channel_id')
                    current_time = datetime.now(timezone.utc).isoformat()
                    
                    # Insert trade record
                    cursor.execute("""
                        INSERT INTO trades (
                            trade_id, channel, channel_id, ticker, strike, option_type, 
                            expiration, entry_time, entry_price, quantity, quantity_remaining, 
                            size_category, status, stop_loss_price, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        trade_id,
                        channel,
                        channel_id,
                        trade_data.get('ticker', ''),
                        float(trade_data.get('strike', 0)),
                        trade_data.get('type', ''),
                        trade_data.get('expiration', ''),
                        current_time,
                        float(trade_data.get('price', 0)),
                        quantity,
                        quantity,  # quantity_remaining starts equal to quantity
                        size_category,
                        'open',
                        trade_data.get('stop_loss_price'),
                        current_time
                    ))
                    
                    # Record entry event
                    cursor.execute("""
                        INSERT INTO trade_events (trade_id, event_type, event_time, quantity, price, notes)
                        VALUES (?, 'entry', ?, ?, ?, ?)
                    """, (
                        trade_id,
                        current_time,
                        quantity,
                        float(trade_data.get('price', 0)),
                        f"Entry in {channel}"
                    ))
                    
                    conn.commit()
                    self.logger.info(f"Recorded entry for {trade_data.get('ticker')} in {channel} (ID: {trade_id})")
                    return trade_id
                    
            except sqlite3.IntegrityError as e:
                if "UNIQUE constraint failed" in str(e):
                    self.logger.warning(f"Trade {trade_id} already exists")
                    return trade_id
                else:
                    self.logger.error(f"Database integrity error: {e}")
                    raise
            except Exception as e:
                self.logger.error(f"Error recording entry: {e}")
                raise
    
    def find_open_trade_by_ticker(self, ticker: str, channel: str = None) -> Optional[str]:
        """
        Find most recent open trade ID by ticker with OPTIONAL channel filtering.
        """
        with self.lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    if channel:
                        # Channel-specific search (preferred for isolation)
                        cursor.execute("""
                            SELECT trade_id FROM trades 
                            WHERE ticker = ? AND channel = ? AND status = 'open'
                            ORDER BY entry_time DESC LIMIT 1
                        """, (ticker, channel))
                        self.logger.debug(f"Searching for {ticker} in channel {channel}")
                    else:
                        # Cross-channel search (fallback)
                        cursor.execute("""
                            SELECT trade_id FROM trades 
                            WHERE ticker = ? AND status = 'open'
                            ORDER BY entry_time DESC LIMIT 1
                        """, (ticker,))
                        self.logger.debug(f"Searching for {ticker} across all channels")
                    
                    result = cursor.fetchone()
                    if result:
                        self.logger.info(f"Found open trade for {ticker}: {result['trade_id']}")
                        return result['trade_id']
                    return None
                    
            except Exception as e:
                self.logger.error(f"Error finding trade by ticker: {e}")
                return None
    
    def record_trim(self, trade_id: str, trim_data: Dict) -> Optional[TradeRecord]:
        """Record a trim action with enhanced tracking"""
        with self.lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Find the trade
                    cursor.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,))
                    trade_row = cursor.fetchone()
                    
                    if not trade_row:
                        # Fallback: try to find by ticker and channel
                        ticker = trim_data.get('ticker')
                        channel = trim_data.get('channel')
                        if ticker and channel:
                            cursor.execute("""
                                SELECT * FROM trades 
                                WHERE ticker = ? AND channel = ? AND status IN ('open', 'partially_trimmed')
                                ORDER BY entry_time DESC LIMIT 1
                            """, (ticker, channel))
                            trade_row = cursor.fetchone()
                            if trade_row:
                                trade_id = trade_row['trade_id']
                                self.logger.info(f"Found trade by ticker for trim: {trade_id}")
                    
                    if not trade_row:
                        self.logger.error(f"Trade {trade_id} not found for trim")
                        return None
                    
                    # Calculate new quantities
                    trim_quantity = trim_data.get('quantity', 1)
                    current_remaining = trade_row['quantity_remaining'] or trade_row['quantity']
                    new_remaining = max(0, current_remaining - trim_quantity)
                    trim_price = float(trim_data.get('price', 0))
                    current_time = datetime.now(timezone.utc).isoformat()
                    
                    # Update trade record
                    new_status = 'partially_trimmed' if new_remaining > 0 else 'trimmed'
                    cursor.execute("""
                        UPDATE trades SET 
                            quantity_remaining = ?,
                            status = ?,
                            updated_at = ?
                        WHERE trade_id = ?
                    """, (new_remaining, new_status, current_time, trade_id))
                    
                    # Record trim event
                    cursor.execute("""
                        INSERT INTO trade_events (trade_id, event_type, event_time, quantity, price, notes)
                        VALUES (?, 'trim', ?, ?, ?, ?)
                    """, (
                        trade_id,
                        current_time,
                        trim_quantity,
                        trim_price,
                        f"Trimmed {trim_quantity} contracts @ ${trim_price:.2f}"
                    ))
                    
                    conn.commit()
                    self.logger.info(f"Recorded trim for {trade_row['ticker']}: {trim_quantity} contracts @ ${trim_price:.2f}")
                    
                    # Return trade record
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
                        exit_price=trim_price,
                        quantity=trade_row['quantity'],
                        size_category=trade_row['size_category'],
                        pnl_dollars=0,
                        pnl_percent=0,
                        status=new_status
                    )
                    
            except Exception as e:
                self.logger.error(f"Error recording trim: {e}")
                return None
    
    def record_exit(self, trade_id: str, exit_data: Dict) -> Optional[TradeRecord]:
        """Record a complete exit with enhanced P&L calculation"""
        with self.lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Find the trade
                    cursor.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,))
                    trade_row = cursor.fetchone()
                    
                    if not trade_row:
                        # Fallback: try to find by ticker and channel
                        ticker = exit_data.get('ticker')
                        channel = exit_data.get('channel')
                        if ticker and channel:
                            cursor.execute("""
                                SELECT * FROM trades 
                                WHERE ticker = ? AND channel = ? AND status IN ('open', 'partially_trimmed')
                                ORDER BY entry_time DESC LIMIT 1
                            """, (ticker, channel))
                            trade_row = cursor.fetchone()
                            if trade_row:
                                trade_id = trade_row['trade_id']
                                self.logger.info(f"Found trade by ticker for exit: {trade_id}")
                    
                    if not trade_row:
                        self.logger.error(f"Trade {trade_id} not found for exit")
                        return None
                    
                    # Calculate P&L
                    entry_time = datetime.fromisoformat(trade_row['entry_time'].replace('Z', '+00:00'))
                    exit_time = datetime.now(timezone.utc)
                    exit_price = float(exit_data.get('price', 0))
                    entry_price = trade_row['entry_price']
                    is_stop_loss = exit_data.get('is_stop_loss', False)
                    
                    # Calculate P&L
                    if exit_price > 0 and entry_price > 0:
                        pnl_percent = ((exit_price - entry_price) / entry_price) * 100
                        remaining_quantity = trade_row['quantity_remaining'] or trade_row['quantity']
                        pnl_dollars = (exit_price - entry_price) * remaining_quantity * 100
                    else:
                        pnl_percent = 0
                        pnl_dollars = 0
                    
                    exit_status = 'stop_loss' if is_stop_loss else 'closed'
                    current_time = exit_time.isoformat()
                    
                    # Update trade record
                    cursor.execute("""
                        UPDATE trades SET 
                            exit_time = ?,
                            exit_price = ?,
                            quantity_remaining = 0,
                            pnl_dollars = ?,
                            pnl_percent = ?,
                            status = ?,
                            updated_at = ?
                        WHERE trade_id = ?
                    """, (
                        current_time,
                        exit_price,
                        pnl_dollars,
                        pnl_percent,
                        exit_status,
                        current_time,
                        trade_id
                    ))
                    
                    # Record exit event
                    cursor.execute("""
                        INSERT INTO trade_events (trade_id, event_type, event_time, quantity, price, notes)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        trade_id,
                        'exit',
                        current_time,
                        trade_row['quantity_remaining'] or trade_row['quantity'],
                        exit_price,
                        f"{'Stop loss' if is_stop_loss else 'Manual exit'} @ ${exit_price:.2f} ({pnl_percent:+.2f}%)"
                    ))
                    
                    # Update performance summary
                    self._update_performance_summary(conn, trade_row['channel'], pnl_percent, pnl_dollars)
                    
                    conn.commit()
                    
                    self.logger.info(f"Recorded exit for {trade_row['ticker']} in {trade_row['channel']}: {pnl_percent:+.2f}%")
                    
                    # Return trade record
                    return TradeRecord(
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
                        status=exit_status
                    )
                    
            except Exception as e:
                self.logger.error(f"Error recording exit: {e}")
                return None
    
    def _update_performance_summary(self, conn, channel: str, pnl_percent: float, pnl_dollars: float):
        """Update daily performance summary"""
        try:
            cursor = conn.cursor()
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            
            # Try to update existing record
            cursor.execute("""
                UPDATE performance_summary SET
                    total_trades = total_trades + 1,
                    winning_trades = winning_trades + CASE WHEN ? > 0 THEN 1 ELSE 0 END,
                    losing_trades = losing_trades + CASE WHEN ? <= 0 THEN 1 ELSE 0 END,
                    total_pnl = total_pnl + ?,
                    best_trade = MAX(best_trade, ?),
                    worst_trade = MIN(worst_trade, ?),
                    updated_at = ?
                WHERE channel = ? AND date = ?
            """, (pnl_percent, pnl_percent, pnl_dollars, pnl_percent, pnl_percent, 
                  datetime.now(timezone.utc).isoformat(), channel, today))
            
            if cursor.rowcount == 0:
                # Insert new record if none exists
                cursor.execute("""
                    INSERT INTO performance_summary 
                    (channel, date, total_trades, winning_trades, losing_trades, 
                     total_pnl, best_trade, worst_trade, updated_at)
                    VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)
                """, (channel, today, 
                      1 if pnl_percent > 0 else 0,
                      0 if pnl_percent > 0 else 1,
                      pnl_dollars, pnl_percent, pnl_percent,
                      datetime.now(timezone.utc).isoformat()))
            
        except Exception as e:
            self.logger.error(f"Error updating performance summary: {e}")
    
    def get_recent_trades(self, limit: int = 10, channel: str = None) -> List[Dict]:
        """Get most recent completed trades with optional channel filtering"""
        with self.lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    if channel:
                        cursor.execute("""
                            SELECT * FROM trades 
                            WHERE channel = ? AND status IN ('closed', 'stop_loss') 
                            ORDER BY exit_time DESC 
                            LIMIT ?
                        """, (channel, limit))
                    else:
                        cursor.execute("""
                            SELECT * FROM trades 
                            WHERE status IN ('closed', 'stop_loss') 
                            ORDER BY exit_time DESC 
                            LIMIT ?
                        """, (limit,))
                    
                    rows = cursor.fetchall()
                    return [dict(row) for row in rows]
                    
            except Exception as e:
                self.logger.error(f"Error getting recent trades: {e}")
                return []
    
    def get_channel_performance(self, channel: str, days: int = 30) -> Dict[str, Any]:
        """Get comprehensive performance metrics for a specific channel"""
        with self.lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Calculate date range
                    end_date = datetime.now(timezone.utc)
                    start_date = end_date - timedelta(days=days)
                    
                    # Get all completed trades for the channel in date range
                    cursor.execute("""
                        SELECT * FROM trades 
                        WHERE channel = ? AND status IN ('closed', 'stop_loss')
                        AND exit_time >= ?
                        ORDER BY exit_time DESC
                    """, (channel, start_date.isoformat()))
                    
                    trades = [dict(row) for row in cursor.fetchall()]
                    
                    if not trades:
                        return {
                            'channel': channel,
                            'total_trades': 0,
                            'win_rate': 0,
                            'avg_return': 0,
                            'total_pnl': 0,
                            'best_trade': 0,
                            'worst_trade': 0,
                            'days_analyzed': days
                        }
                    
                    # Calculate metrics
                    winning_trades = [t for t in trades if t.get('pnl_percent', 0) > 0]
                    losing_trades = [t for t in trades if t.get('pnl_percent', 0) <= 0]
                    
                    total_trades = len(trades)
                    win_rate = (len(winning_trades) / total_trades) * 100 if total_trades > 0 else 0
                    
                    # Calculate average return
                    returns = [t.get('pnl_percent', 0) for t in trades]
                    avg_return = sum(returns) / len(returns) if returns else 0
                    
                    # Calculate total P&L
                    total_pnl = sum(t.get('pnl_dollars', 0) for t in trades)
                    
                    # Best and worst trades
                    best_trade = max(returns) if returns else 0
                    worst_trade = min(returns) if returns else 0
                    
                    # Calculate Sharpe ratio (simplified)
                    if len(returns) > 1:
                        import statistics
                        try:
                            return_std = statistics.stdev(returns)
                            sharpe_ratio = (avg_return / return_std) if return_std > 0 else 0
                        except:
                            sharpe_ratio = 0
                    else:
                        sharpe_ratio = 0
                    
                    return {
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
                    
            except Exception as e:
                self.logger.error(f"Error getting channel performance: {e}")
                return {'channel': channel, 'error': str(e)}
    
    def get_open_trades_for_channel(self, channel: str) -> List[Dict]:
        """Get all open trades for a specific channel"""
        with self.lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        SELECT * FROM trades 
                        WHERE channel = ? AND status IN ('open', 'partially_trimmed')
                        ORDER BY entry_time DESC
                    """, (channel,))
                    
                    rows = cursor.fetchall()
                    return [dict(row) for row in rows]
                    
            except Exception as e:
                self.logger.error(f"Error getting open trades for channel {channel}: {e}")
                return []

    def close_all_channel_positions(self, channel: str, reason: str = "Manual clear") -> int:
        """Close all open positions for a specific channel by setting their status to 'cleared'"""
        with self.lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # First, get the count of positions that will be cleared
                    cursor.execute("""
                        SELECT COUNT(*) FROM trades 
                        WHERE channel = ? AND status IN ('open', 'partially_trimmed')
                    """, (channel,))
                    
                    count_before = cursor.fetchone()[0]
                    
                    if count_before == 0:
                        return 0
                    
                    # Update all open positions to 'cleared' status
                    cursor.execute("""
                        UPDATE trades 
                        SET status = 'cleared',
                            exit_time = CURRENT_TIMESTAMP,
                            exit_price = 0.0,
                            pnl_percent = 0.0,
                            pnl_dollars = 0.0,
                            notes = CASE 
                                WHEN notes IS NULL OR notes = '' THEN ?
                                ELSE notes || '; ' || ?
                            END
                        WHERE channel = ? AND status IN ('open', 'partially_trimmed')
                    """, (reason, reason, channel))
                    
                    cleared_count = cursor.rowcount
                    
                    # Log the clearing action
                    self.logger.info(f"Cleared {cleared_count} positions for channel {channel}: {reason}")
                    
                    # Force commit the changes
                    conn.commit()
                    
                    return cleared_count
                    
            except Exception as e:
                self.logger.error(f"Error closing all positions for channel {channel}: {e}")
                return 0
    
    def cleanup_old_trades(self, days: int = 90):
        """Archive old closed trades to keep database performant"""
        with self.lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
                    
                    # Archive old trades
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS trades_archive AS 
                        SELECT * FROM trades WHERE 1=0
                    """)
                    
                    cursor.execute("""
                        INSERT INTO trades_archive 
                        SELECT * FROM trades 
                        WHERE status IN ('closed', 'stop_loss') 
                        AND exit_time < ?
                    """, (cutoff_date,))
                    
                    archived_count = cursor.rowcount
                    
                    # Delete archived trades from main table
                    cursor.execute("""
                        DELETE FROM trades 
                        WHERE status IN ('closed', 'stop_loss') 
                        AND exit_time < ?
                    """, (cutoff_date,))
                    
                    # Also clean up old events
                    cursor.execute("""
                        DELETE FROM trade_events 
                        WHERE event_time < ?
                        AND trade_id NOT IN (SELECT trade_id FROM trades)
                    """, (cutoff_date,))
                    
                    conn.commit()
                    
                    if archived_count > 0:
                        self.logger.info(f"Archived {archived_count} old trades (older than {days} days)")
                        print(f"🧹 Archived {archived_count} old trades")
                    
                    return archived_count
                    
            except Exception as e:
                self.logger.error(f"Error during cleanup: {e}")
                return 0
    
    def export_trades_csv(self, filename: str = None, channel: str = None):
        """Export trades to CSV for analysis"""
        import csv
        
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            channel_suffix = f"_{channel}" if channel else ""
            filename = f"trades_export{channel_suffix}_{timestamp}.csv"
        
        with self.lock:
            try:
                with self._get_connection() as conn:
                   cursor = conn.cursor()
                   
                   if channel:
                       cursor.execute("SELECT * FROM trades WHERE channel = ? ORDER BY entry_time", (channel,))
                   else:
                       cursor.execute("SELECT * FROM trades ORDER BY entry_time")
                   
                   trades = cursor.fetchall()
                   
                   if not trades:
                       print(f"📊 No trades to export for {channel if channel else 'all channels'}")
                       return
                   
                   # Write to CSV
                   with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                       # Get column names from the first row
                       fieldnames = trades[0].keys()
                       writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                       writer.writeheader()
                       for trade in trades:
                           writer.writerow(dict(trade))
                   
                   print(f"📊 Exported {len(trades)} trades to {filename}")
                   self.logger.info(f"Exported {len(trades)} trades to {filename}")
                   
            except Exception as e:
                self.logger.error(f"Error exporting trades: {e}")
                print(f"❌ Error exporting trades: {e}")
   
    def get_trade_events(self, trade_id: str) -> List[Dict]:
        """Get all events for a specific trade"""
        with self.lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        SELECT * FROM trade_events 
                        WHERE trade_id = ? 
                        ORDER BY event_time
                    """, (trade_id,))
                    
                    events = [dict(row) for row in cursor.fetchall()]
                    return events
                   
            except Exception as e:
                self.logger.error(f"Error getting trade events: {e}")
                return []
   
    def get_performance_summary(self, channel: str = None, days: int = 30) -> Dict[str, Any]:
        """Get aggregated performance summary"""
        with self.lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
                    
                    if channel:
                        cursor.execute("""
                            SELECT 
                                SUM(total_trades) as total_trades,
                                SUM(winning_trades) as winning_trades,
                                SUM(losing_trades) as losing_trades,
                                SUM(total_pnl) as total_pnl,
                                MAX(best_trade) as best_trade,
                                MIN(worst_trade) as worst_trade
                            FROM performance_summary
                            WHERE channel = ? AND date >= ?
                        """, (channel, start_date))
                    else:
                        cursor.execute("""
                            SELECT 
                                SUM(total_trades) as total_trades,
                                SUM(winning_trades) as winning_trades,
                                SUM(losing_trades) as losing_trades,
                                SUM(total_pnl) as total_pnl,
                                MAX(best_trade) as best_trade,
                                MIN(worst_trade) as worst_trade
                            FROM performance_summary
                            WHERE date >= ?
                        """, (start_date,))
                    
                    result = cursor.fetchone()
                    
                    if result and result['total_trades']:
                        total_trades = result['total_trades'] or 0
                        winning_trades = result['winning_trades'] or 0
                        losing_trades = result['losing_trades'] or 0
                        
                        return {
                            'channel': channel or 'All Channels',
                            'total_trades': total_trades,
                            'winning_trades': winning_trades,
                            'losing_trades': losing_trades,
                            'win_rate': (winning_trades / total_trades * 100) if total_trades > 0 else 0,
                            'total_pnl': result['total_pnl'] or 0,
                            'best_trade': result['best_trade'] or 0,
                            'worst_trade': result['worst_trade'] or 0,
                            'days_analyzed': days
                        }
                    else:
                        return {
                            'channel': channel or 'All Channels',
                            'total_trades': 0,
                            'winning_trades': 0,
                            'losing_trades': 0,
                            'win_rate': 0,
                            'total_pnl': 0,
                            'best_trade': 0,
                            'worst_trade': 0,
                            'days_analyzed': days
                        }
                   
            except Exception as e:
                self.logger.error(f"Error getting performance summary: {e}")
                return {'error': str(e)}
   
    def repair_database(self):
        """Attempt to repair database issues"""
        with self.lock:
            try:
                print("🔧 Attempting database repair...")
                self.logger.info("Starting database repair")
                
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Fix any NULL quantity_remaining values
                    cursor.execute("""
                        UPDATE trades 
                        SET quantity_remaining = quantity 
                        WHERE quantity_remaining IS NULL AND status = 'open'
                    """)
                    fixed_qty = cursor.rowcount
                    
                    # Fix any NULL updated_at values
                    cursor.execute("""
                        UPDATE trades 
                        SET updated_at = created_at 
                        WHERE updated_at IS NULL
                    """)
                    fixed_dates = cursor.rowcount
                    
                    # Fix orphaned partially_trimmed trades (no events)
                    cursor.execute("""
                        UPDATE trades 
                        SET status = 'open' 
                        WHERE status = 'partially_trimmed' 
                        AND trade_id NOT IN (
                            SELECT DISTINCT trade_id 
                            FROM trade_events 
                            WHERE event_type = 'trim'
                        )
                    """)
                    fixed_status = cursor.rowcount
                    
                    # Remove duplicate trade events
                    cursor.execute("""
                        DELETE FROM trade_events 
                        WHERE rowid NOT IN (
                            SELECT MIN(rowid) 
                            FROM trade_events 
                            GROUP BY trade_id, event_type, event_time
                        )
                    """)
                    removed_duplicates = cursor.rowcount
                    
                    # Vacuum the database
                    conn.commit()
                    cursor.execute("VACUUM")
                    cursor.execute("ANALYZE")
                    
                    repair_summary = f"""
                    Database Repair Complete:
                    - Fixed quantity_remaining: {fixed_qty}
                    - Fixed updated_at dates: {fixed_dates}
                    - Fixed orphaned status: {fixed_status}
                    - Removed duplicate events: {removed_duplicates}
                    """
                    
                    print(f"✅ {repair_summary}")
                    self.logger.info(repair_summary)
                    
                    return True
                   
            except Exception as e:
                self.logger.error(f"Database repair failed: {e}")
                print(f"❌ Database repair failed: {e}")
                return False
   
    def get_statistics(self) -> Dict[str, Any]:
        """Get overall database statistics"""
        with self.lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    stats = {}
                    
                    # Total trades
                    cursor.execute("SELECT COUNT(*) as count FROM trades")
                    stats['total_trades'] = cursor.fetchone()['count']
                    
                    # Open trades
                    cursor.execute("SELECT COUNT(*) as count FROM trades WHERE status = 'open'")
                    stats['open_trades'] = cursor.fetchone()['count']
                    
                    # Closed trades
                    cursor.execute("SELECT COUNT(*) as count FROM trades WHERE status IN ('closed', 'stop_loss')")
                    stats['closed_trades'] = cursor.fetchone()['count']
                    
                    # Total events
                    cursor.execute("SELECT COUNT(*) as count FROM trade_events")
                    stats['total_events'] = cursor.fetchone()['count']
                    
                    # Unique channels
                    cursor.execute("SELECT COUNT(DISTINCT channel) as count FROM trades")
                    stats['unique_channels'] = cursor.fetchone()['count']
                    
                    # Database size
                    cursor.execute("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
                    stats['database_size_bytes'] = cursor.fetchone()['size']
                    stats['database_size_mb'] = round(stats['database_size_bytes'] / (1024 * 1024), 2)
                    
                    # Date range
                    cursor.execute("SELECT MIN(entry_time) as min_date, MAX(entry_time) as max_date FROM trades")
                    result = cursor.fetchone()
                    if result and result['min_date']:
                        stats['first_trade'] = result['min_date']
                        stats['last_trade'] = result['max_date']
                    
                    return stats
                   
            except Exception as e:
                self.logger.error(f"Error getting statistics: {e}")
                return {'error': str(e)}

# Compatibility export
__all__ = ['EnhancedPerformanceTracker', 'TradeRecord']