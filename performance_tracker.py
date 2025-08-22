# performance_tracker.py - Enhanced Performance Tracking with Channel Isolation
import sqlite3
import logging
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

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
    
    def __init__(self, db_file: str = "performance_tracking.db"):
        self.db_file = db_file
        self.lock = Lock()
        
        # Setup logging
        self.logger = logging.getLogger('performance_tracker')
        self.logger.setLevel(logging.DEBUG)
        
        if not self.logger.handlers:
            # Create logs directory if it doesn't exist
            import os
            if not os.path.exists('logs'):
                os.makedirs('logs')
            handler = logging.FileHandler("logs/performance_tracker.log")
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            
        self._initialize_database()
        print("✅ Enhanced Performance Tracker initialized with channel isolation")
    
    def _initialize_database(self):
        """Initialize the SQLite database with enhanced schema"""
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            
            # Enhanced trades table with better channel tracking
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
                    trailing_stop_active BOOLEAN DEFAULT 0,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Add new columns if they don't exist
            cursor.execute("PRAGMA table_info(trades)")
            columns = [column[1] for column in cursor.fetchall()]
            
            # --- FIX: Removed DEFAULT CURRENT_TIMESTAMP from updated_at ---
            new_columns = [
                ('channel_id', 'INTEGER'),
                ('quantity_remaining', 'INTEGER DEFAULT 0'),
                ('stop_loss_price', 'REAL'),
                ('trailing_stop_active', 'BOOLEAN DEFAULT 0'),
                ('notes', 'TEXT'),
                ('updated_at', 'TEXT') # Default is handled by CREATE TABLE, cannot be in ALTER
            ]
            # --- END FIX ---
            
            for col_name, col_type in new_columns:
                if col_name not in columns:
                    self.logger.info(f"Adding {col_name} column...")
                    cursor.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")
            
            # Update existing records if needed
            cursor.execute("UPDATE trades SET quantity_remaining = quantity WHERE status = 'open' AND quantity_remaining = 0")
            cursor.execute("UPDATE trades SET updated_at = created_at WHERE updated_at IS NULL")
            
            # Create indexes for better performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_channel ON trades(channel)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_channel_ticker ON trades(channel, ticker)")
            
            # Trade history table for detailed tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    quantity INTEGER,
                    price REAL,
                    notes TEXT,
                    FOREIGN KEY (trade_id) REFERENCES trades (trade_id)
                )
            """)
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_trade_id ON trade_events(trade_id)")
            
            conn.commit()
            conn.close()
    
    def record_entry(self, trade_data: Dict) -> str:
        """Record a new trade entry with enhanced channel tracking"""
        with self.lock:
            trade_id = trade_data.get('trade_id') or f"trade_{int(datetime.now().timestamp() * 1000)}"
            
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            
            try:
                quantity = trade_data.get('quantity', 1)
                size_category = trade_data.get('size', 'full')
                channel = trade_data.get('channel', 'Unknown')
                channel_id = trade_data.get('channel_id')
                
                cursor.execute("""
                    INSERT INTO trades (
                        trade_id, channel, channel_id, ticker, strike, option_type, expiration,
                        entry_time, entry_price, quantity, quantity_remaining, 
                        size_category, status, stop_loss_price, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
                """, (
                    trade_id,
                    channel,
                    channel_id,
                    trade_data.get('ticker', ''),
                    trade_data.get('strike', 0),
                    trade_data.get('type', ''),
                    trade_data.get('expiration', ''),
                    datetime.now(timezone.utc).isoformat(),
                    trade_data.get('price', 0),
                    quantity,
                    quantity,
                    size_category,
                    trade_data.get('stop_loss_price'),
                    datetime.now(timezone.utc).isoformat()
                ))
                
                # Record entry event
                cursor.execute("""
                    INSERT INTO trade_events (trade_id, event_type, event_time, quantity, price, notes)
                    VALUES (?, 'entry', ?, ?, ?, ?)
                """, (
                    trade_id,
                    datetime.now(timezone.utc).isoformat(),
                    quantity,
                    trade_data.get('price', 0),
                    f"Entry in {channel}"
                ))
                
                conn.commit()
                self.logger.info(f"Recorded entry for {trade_data.get('ticker')} in {channel} (ID: {trade_id})")
                
            except sqlite3.IntegrityError:
                self.logger.warning(f"Trade {trade_id} already exists")
            except Exception as e:
                self.logger.error(f"Error recording entry: {e}")
                conn.rollback()
            finally:
                conn.close()
            
            return trade_id
    
    def find_open_trade_by_ticker(self, ticker: str, channel: str = None) -> Optional[str]:
        """
        Find most recent open trade ID by ticker with OPTIONAL channel filtering.
        If channel is provided, searches only within that channel.
        If channel is None, searches across all channels.
        """
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            
            try:
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
                    self.logger.info(f"Found open trade for {ticker}: {result[0]}")
                return result[0] if result else None
                
            except Exception as e:
                self.logger.error(f"Error finding trade by ticker: {e}")
                return None
            finally:
                conn.close()
    
    def get_open_trades_for_channel(self, channel: str) -> List[Dict]:
        """Get all open trades for a specific channel"""
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    SELECT * FROM trades 
                    WHERE channel = ? AND status = 'open'
                    ORDER BY entry_time DESC
                """, (channel,))
                
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
                
            except Exception as e:
                self.logger.error(f"Error getting open trades for channel {channel}: {e}")
                return []
            finally:
                conn.close()
    
    def record_trim(self, trade_id: str, trim_data: Dict) -> Optional[TradeRecord]:
        """Record a trim action with enhanced tracking"""
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            try:
                cursor.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,))
                trade_row = cursor.fetchone()
                
                if not trade_row:
                    # Fallback: try to find by ticker in the same channel
                    ticker = trim_data.get('ticker')
                    channel = trim_data.get('channel')
                    if ticker and channel:
                        cursor.execute("""
                            SELECT * FROM trades 
                            WHERE ticker = ? AND channel = ? AND status = 'open'
                            ORDER BY entry_time DESC LIMIT 1
                        """, (ticker, channel))
                        trade_row = cursor.fetchone()
                        if trade_row:
                            trade_id = trade_row['trade_id']
                            self.logger.info(f"Found trade by ticker for trim: {trade_id}")
                
                if not trade_row:
                    self.logger.error(f"Trade {trade_id} not found for trim")
                    return None
                
                trim_quantity = trim_data.get('quantity', 1)
                current_remaining = trade_row['quantity_remaining']
                new_remaining = max(0, current_remaining - trim_quantity)
                trim_price = trim_data.get('price', 0)
                
                cursor.execute("""
                    UPDATE trades SET 
                        quantity_remaining = ?,
                        status = CASE WHEN ? > 0 THEN 'partially_trimmed' ELSE 'trimmed' END,
                        updated_at = ?
                    WHERE trade_id = ?
                """, (new_remaining, new_remaining, datetime.now(timezone.utc).isoformat(), trade_id))
                
                # Record trim event
                cursor.execute("""
                    INSERT INTO trade_events (trade_id, event_type, event_time, quantity, price, notes)
                    VALUES (?, 'trim', ?, ?, ?, ?)
                """, (
                    trade_id,
                    datetime.now(timezone.utc).isoformat(),
                    trim_quantity,
                    trim_price,
                    f"Trimmed {trim_quantity} contracts @ ${trim_price:.2f}"
                ))
                
                conn.commit()
                self.logger.info(f"Recorded trim for {trade_row['ticker']}: {trim_quantity} contracts @ ${trim_price:.2f}")
                
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
                    status='partially_trimmed'
                )
                
            except Exception as e:
                self.logger.error(f"Error recording trim: {e}")
                conn.rollback()
                return None
            finally:
                conn.close()
    
    def record_exit(self, trade_id: str, exit_data: Dict) -> Optional[TradeRecord]:
        """Record a complete exit with enhanced P&L calculation"""
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            try:
                cursor.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,))
                trade_row = cursor.fetchone()
                
                if not trade_row:
                    # Fallback: try to find by ticker in the same channel
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
                
                entry_time = datetime.fromisoformat(trade_row['entry_time'].replace('Z', '+00:00'))
                exit_time = datetime.now(timezone.utc)
                exit_price = exit_data.get('price', 0)
                entry_price = trade_row['entry_price']
                is_stop_loss = exit_data.get('is_stop_loss', False)
                
                # Enhanced P&L calculation
                if exit_price > 0 and entry_price > 0:
                    pnl_percent = ((exit_price - entry_price) / entry_price) * 100
                    remaining_quantity = trade_row.get('quantity_remaining', trade_row['quantity'])
                    pnl_dollars = (exit_price - entry_price) * remaining_quantity * 100
                else:
                    pnl_percent = 0
                    pnl_dollars = 0
                
                exit_status = 'stop_loss' if is_stop_loss else 'closed'
                
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
                    exit_time.isoformat(),
                    exit_price,
                    pnl_dollars,
                    pnl_percent,
                    exit_status,
                    datetime.now(timezone.utc).isoformat(),
                    trade_id
                ))
                
                # Record exit event
                cursor.execute("""
                    INSERT INTO trade_events (trade_id, event_type, event_time, quantity, price, notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    trade_id,
                    'exit',
                    exit_time.isoformat(),
                    trade_row.get('quantity_remaining', trade_row['quantity']),
                    exit_price,
                    f"{'Stop loss' if is_stop_loss else 'Manual exit'} @ ${exit_price:.2f} ({pnl_percent:+.2f}%)"
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
                    status=exit_status
                )
                
                self.logger.info(f"Recorded exit for {trade_row['ticker']} in {trade_row['channel']}: {pnl_percent:+.2f}%")
                
                return trade_record
                
            except Exception as e:
                self.logger.error(f"Error recording exit: {e}")
                conn.rollback()
                return None
            finally:
                conn.close()
    
    def get_recent_trades(self, limit: int = 10, channel: str = None) -> List[Dict]:
        """Get most recent completed trades with optional channel filtering"""
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            try:
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
            finally:
                conn.close()
    
    def get_channel_performance(self, channel: str) -> Dict[str, Any]:
        """Get comprehensive performance metrics for a specific channel"""
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            try:
                # Get all completed trades for the channel
                cursor.execute("""
                    SELECT * FROM trades 
                    WHERE channel = ? AND status IN ('closed', 'stop_loss')
                    ORDER BY exit_time DESC
                """, (channel,))
                
                trades = [dict(row) for row in cursor.fetchall()]
                
                if not trades:
                    return {
                        'channel': channel,
                        'total_trades': 0,
                        'win_rate': 0,
                        'avg_return': 0,
                        'total_pnl': 0,
                        'best_trade': 0,
                        'worst_trade': 0
                    }
                
                # Calculate metrics
                winning_trades = [t for t in trades if t.get('pnl_percent', 0) > 0]
                losing_trades = [t for t in trades if t.get('pnl_percent', 0) <= 0]
                
                total_trades = len(trades)
                win_rate = (len(winning_trades) / total_trades) * 100 if total_trades > 0 else 0
                avg_return = sum(t.get('pnl_percent', 0) for t in trades) / total_trades if total_trades > 0 else 0
                total_pnl = sum(t.get('pnl_dollars', 0) for t in trades)
                best_trade = max(t.get('pnl_percent', 0) for t in trades) if trades else 0
                worst_trade = min(t.get('pnl_percent', 0) for t in trades) if trades else 0
                
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
                    'recent_trades': trades[:5]
                }
                
            except Exception as e:
                self.logger.error(f"Error getting channel performance: {e}")
                return {}
            finally:
                conn.close()
    
    def export_trades_csv(self, filename: str = None, channel: str = None):
        """Export trades to CSV for analysis"""
        import csv
        
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            channel_suffix = f"_{channel}" if channel else ""
            filename = f"trades_export{channel_suffix}_{timestamp}.csv"
        
        with self.lock:
            conn = sqlite3.connect(self.db_file)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            try:
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
                    fieldnames = trades[0].keys()
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    for trade in trades:
                        writer.writerow(dict(trade))
                
                print(f"📊 Exported {len(trades)} trades to {filename}")
                
            except Exception as e:
                self.logger.error(f"Error exporting trades: {e}")
            finally:
                conn.close()