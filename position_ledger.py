# position_ledger.py - Persistent Position Ledger with SQLite
"""
SQLite-backed position ledger for tracking open option positions.
Enables resolution of generic alerts like "Trim SPY" to specific contracts.

Architecture:
    - Database: SQLite at logs/position_ledger.db (configurable via POSITION_LEDGER_DB)
    - CCID Format: {TICKER}_{YYYYMMDD}_{STRIKE}_{C/P} (e.g., SPY_20260128_595_C)
    - Tables: positions (main tracking), position_lots (lot-level for averaging)

Key Features:
    - Persistent position memory across restarts
    - Lot-level tracking for position averaging (FIFO selling)
    - Weighted hint matching for generic alert resolution
    - Configurable heuristics: fifo, nearest, profit, largest
    - Lock mechanism to prevent concurrent double-sells
    - Periodic reconciliation with Robinhood API

Integration:
    - Initialized in main.py, passed to TradeExecutor
    - record_buy() called after successful buy orders
    - resolve_position() called before trim/exit to get contract details
    - record_sell() called after successful sell orders
    - sync_from_robinhood() runs on startup and periodically

Configuration (config.py):
    - POSITION_LEDGER_DB: Database file path
    - LEDGER_SYNC_INTERVAL: Reconciliation interval in seconds
    - LEDGER_HEURISTIC_STRATEGY: Default heuristic (fifo/nearest/profit/largest)
    - LEDGER_LOCK_TIMEOUT: Lock timeout for pending exits
"""

import sqlite3
import logging
import random
from datetime import datetime, date, timedelta
from pathlib import Path
from threading import Lock
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass, asdict
from contextlib import contextmanager

from config import get_trader_symbol, get_all_symbol_variants, LEDGER_HEURISTIC_STRATEGY

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_DB_PATH = "logs/position_ledger.db"


@dataclass
class Position:
    """Represents an open position in the ledger."""
    ccid: str
    ticker: str
    strike: float
    option_type: str
    expiration: str
    total_quantity: int
    avg_cost_basis: float
    status: str
    channel: Optional[str]
    first_entry_time: str
    last_update_time: str
    pending_exit_since: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PositionLot:
    """Represents a single lot (entry) within a position."""
    lot_id: str
    ccid: str
    quantity: int
    cost_basis: float
    entry_time: str
    source_trade_id: Optional[str]
    status: str
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SyncResult:
    """Result of syncing with Robinhood."""
    positions_added: int
    positions_updated: int
    positions_orphaned: int
    errors: List[str]


class PositionLedger:
    """
    SQLite-backed position ledger for tracking open option positions.

    Features:
    - CCID (Canonical Contract ID) for unique identification
    - Lot-level tracking for position averaging
    - Weighted matching for resolving generic alerts
    - Heuristics: FIFO, nearest-expiry, profit-first
    - Lock mechanism to prevent double-sells
    - Robinhood API reconciliation
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        """Initialize the position ledger with SQLite database."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()  # Thread safety for concurrent access
        self._init_db()
        self._verify_database_integrity()
        logger.info(f"Position ledger initialized at {self.db_path}")

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def _verify_database_integrity(self):
        """Verify database integrity on startup."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check")
                result = cursor.fetchone()
                if result[0] != "ok":
                    logger.error(f"Database integrity check failed: {result[0]}")
                else:
                    logger.debug("Database integrity check passed")
        except Exception as e:
            logger.error(f"Database integrity check error: {e}")

    def _init_db(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Positions table - main position tracking
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ccid TEXT NOT NULL UNIQUE,
                    ticker TEXT NOT NULL,
                    strike REAL NOT NULL,
                    option_type TEXT NOT NULL,
                    expiration TEXT NOT NULL,
                    total_quantity INTEGER NOT NULL DEFAULT 0,
                    avg_cost_basis REAL,
                    status TEXT NOT NULL DEFAULT 'open',
                    pending_exit_since TEXT,
                    channel TEXT,
                    first_entry_time TEXT NOT NULL,
                    last_update_time TEXT NOT NULL,
                    notes TEXT,
                    UNIQUE(ticker, expiration, strike, option_type)
                )
            ''')

            # Position lots table - individual entries for averaging
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS position_lots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ccid TEXT NOT NULL,
                    lot_id TEXT NOT NULL UNIQUE,
                    quantity INTEGER NOT NULL,
                    cost_basis REAL NOT NULL,
                    entry_time TEXT NOT NULL,
                    source_trade_id TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    exit_time TEXT,
                    exit_price REAL,
                    FOREIGN KEY (ccid) REFERENCES positions(ccid)
                )
            ''')

            # Create indexes for fast lookups
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_positions_ticker ON positions(ticker)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_positions_expiration ON positions(expiration)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_lots_ccid ON position_lots(ccid)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_lots_status ON position_lots(status)')

            logger.debug("Database schema initialized")

    @staticmethod
    def generate_ccid(ticker: str, expiration: str, strike: float, option_type: str) -> str:
        """
        Generate Canonical Contract ID.
        Format: {TICKER}_{YYYYMMDD}_{STRIKE}_{C/P}
        Example: SPY_20260128_595_C
        """
        # Normalize ticker (use trader symbol, not broker symbol)
        normalized_ticker = get_trader_symbol(ticker.upper())

        # Normalize expiration to YYYYMMDD
        if '-' in expiration:
            exp_date = datetime.strptime(expiration, '%Y-%m-%d')
        else:
            exp_date = datetime.strptime(expiration, '%Y%m%d')
        exp_str = exp_date.strftime('%Y%m%d')

        # Normalize option type
        opt_char = 'C' if option_type.lower() in ('call', 'c') else 'P'

        # Format strike (remove trailing zeros)
        strike_str = f"{float(strike):g}"

        return f"{normalized_ticker}_{exp_str}_{strike_str}_{opt_char}"

    @staticmethod
    def generate_lot_id() -> str:
        """Generate unique lot ID with random suffix to prevent duplicates."""
        return f"lot_{int(datetime.now().timestamp() * 1000)}_{random.randint(0, 999)}"

    def _row_to_position(self, row: sqlite3.Row) -> Position:
        """Convert database row to Position object."""
        return Position(
            ccid=row['ccid'],
            ticker=row['ticker'],
            strike=row['strike'],
            option_type=row['option_type'],
            expiration=row['expiration'],
            total_quantity=row['total_quantity'],
            avg_cost_basis=row['avg_cost_basis'],
            status=row['status'],
            channel=row['channel'],
            first_entry_time=row['first_entry_time'],
            last_update_time=row['last_update_time'],
            pending_exit_since=row['pending_exit_since'],
            notes=row['notes']
        )

    def _row_to_lot(self, row: sqlite3.Row) -> PositionLot:
        """Convert database row to PositionLot object."""
        return PositionLot(
            lot_id=row['lot_id'],
            ccid=row['ccid'],
            quantity=row['quantity'],
            cost_basis=row['cost_basis'],
            entry_time=row['entry_time'],
            source_trade_id=row['source_trade_id'],
            status=row['status'],
            exit_time=row['exit_time'],
            exit_price=row['exit_price']
        )

    # ==================== CRUD OPERATIONS ====================

    def record_buy(self, trade_data: dict) -> str:
        """
        Record a buy order. Creates new position or averages into existing.

        Args:
            trade_data: Dict with keys:
                - ticker: str (e.g., 'SPY')
                - strike: float
                - type: str ('call' or 'put')
                - expiration: str (YYYY-MM-DD)
                - price: float (entry price per contract)
                - quantity: int
                - trade_id: str (optional, for linking to performance tracker)
                - channel: str (optional)

        Returns:
            CCID of the position
        """
        with self.lock:
            ticker = trade_data.get('ticker') or trade_data.get('trader_symbol')
            strike = float(trade_data['strike'])
            option_type = trade_data['type']
            expiration = trade_data['expiration']
            price = float(trade_data['price'])
            quantity = int(trade_data.get('quantity', 1))
            trade_id = trade_data.get('trade_id')
            channel = trade_data.get('channel')

            ccid = self.generate_ccid(ticker, expiration, strike, option_type)
            now = datetime.now().isoformat()
            lot_id = self.generate_lot_id()

            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Check if position already exists
                cursor.execute('SELECT * FROM positions WHERE ccid = ?', (ccid,))
                existing = cursor.fetchone()

                if existing:
                    # Average into existing position
                    old_qty = existing['total_quantity']
                    old_cost = existing['avg_cost_basis'] or 0
                    new_total_qty = old_qty + quantity
                    new_avg_cost = ((old_qty * old_cost) + (quantity * price)) / new_total_qty

                    cursor.execute('''
                        UPDATE positions
                        SET total_quantity = ?,
                            avg_cost_basis = ?,
                            last_update_time = ?,
                            status = 'open'
                        WHERE ccid = ?
                    ''', (new_total_qty, new_avg_cost, now, ccid))

                    logger.info(f"Averaged into position {ccid}: +{quantity} @ ${price:.2f}, "
                               f"new total: {new_total_qty} @ ${new_avg_cost:.2f}")
                else:
                    # Create new position
                    normalized_ticker = get_trader_symbol(ticker.upper())
                    cursor.execute('''
                        INSERT INTO positions
                        (ccid, ticker, strike, option_type, expiration, total_quantity,
                         avg_cost_basis, status, channel, first_entry_time, last_update_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
                    ''', (ccid, normalized_ticker, strike, option_type, expiration,
                          quantity, price, channel, now, now))

                    logger.info(f"Created new position {ccid}: {quantity} @ ${price:.2f}")

                # Always create a lot record for this entry
                cursor.execute('''
                    INSERT INTO position_lots
                    (ccid, lot_id, quantity, cost_basis, entry_time, source_trade_id, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'open')
                ''', (ccid, lot_id, quantity, price, now, trade_id))

                logger.debug(f"Created lot {lot_id} for {ccid}")

            return ccid

    def record_sell(self, ccid: str, quantity: int, price: float,
                    use_fifo: bool = True) -> bool:
        """
        Record a sell (trim or full exit).

        Args:
            ccid: Canonical Contract ID
            quantity: Number of contracts to sell
            price: Exit price per contract
            use_fifo: If True, mark oldest lots as sold first

        Returns:
            True if successful, False otherwise
        """
        with self.lock:
            now = datetime.now().isoformat()

            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Get current position
                cursor.execute('SELECT * FROM positions WHERE ccid = ?', (ccid,))
                position = cursor.fetchone()

                if not position:
                    logger.error(f"Cannot sell - position not found: {ccid}")
                    return False

                current_qty = position['total_quantity']
                if quantity > current_qty:
                    logger.warning(f"Sell qty ({quantity}) > position qty ({current_qty}), "
                                  f"adjusting to {current_qty}")
                    quantity = current_qty

                new_qty = current_qty - quantity
                new_status = 'closed' if new_qty == 0 else 'open'

                # Update position
                cursor.execute('''
                    UPDATE positions
                    SET total_quantity = ?,
                        status = ?,
                        pending_exit_since = NULL,
                        last_update_time = ?
                    WHERE ccid = ?
                ''', (new_qty, new_status, now, ccid))

                # Mark lots as sold (FIFO)
                if use_fifo:
                    remaining_to_sell = quantity
                    cursor.execute('''
                        SELECT * FROM position_lots
                        WHERE ccid = ? AND status = 'open'
                        ORDER BY entry_time ASC
                    ''', (ccid,))
                    lots = cursor.fetchall()

                    for lot in lots:
                        if remaining_to_sell <= 0:
                            break

                        lot_qty = lot['quantity']
                        if lot_qty <= remaining_to_sell:
                            # Sell entire lot
                            cursor.execute('''
                                UPDATE position_lots
                                SET status = 'sold', exit_time = ?, exit_price = ?
                                WHERE lot_id = ?
                            ''', (now, price, lot['lot_id']))
                            remaining_to_sell -= lot_qty
                        else:
                            # Partial lot sale - split the lot
                            sold_qty = remaining_to_sell
                            remaining_qty = lot_qty - sold_qty

                            # Update original lot to sold portion
                            cursor.execute('''
                                UPDATE position_lots
                                SET quantity = ?, status = 'sold', exit_time = ?, exit_price = ?
                                WHERE lot_id = ?
                            ''', (sold_qty, now, price, lot['lot_id']))

                            # Create new lot for remaining
                            new_lot_id = self.generate_lot_id()
                            cursor.execute('''
                                INSERT INTO position_lots
                                (ccid, lot_id, quantity, cost_basis, entry_time, source_trade_id, status)
                                VALUES (?, ?, ?, ?, ?, ?, 'open')
                            ''', (ccid, new_lot_id, remaining_qty, lot['cost_basis'],
                                  lot['entry_time'], lot['source_trade_id']))

                            remaining_to_sell = 0

                logger.info(f"Recorded sell for {ccid}: {quantity} @ ${price:.2f}, "
                           f"remaining: {new_qty}, status: {new_status}")

            return True

    def get_open_positions(self, ticker: str = None) -> List[Position]:
        """
        Get all open positions, optionally filtered by ticker.

        Args:
            ticker: Optional ticker to filter by (handles symbol variants)

        Returns:
            List of Position objects
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if ticker:
                # Get all symbol variants for matching
                variants = get_all_symbol_variants(ticker.upper())
                placeholders = ','.join('?' * len(variants))
                cursor.execute(f'''
                    SELECT * FROM positions
                    WHERE status = 'open' AND ticker IN ({placeholders})
                    ORDER BY first_entry_time ASC
                ''', variants)
            else:
                cursor.execute('''
                    SELECT * FROM positions
                    WHERE status = 'open'
                    ORDER BY first_entry_time ASC
                ''')

            rows = cursor.fetchall()
            return [self._row_to_position(row) for row in rows]

    def get_position_by_ccid(self, ccid: str) -> Optional[Position]:
        """Get a specific position by CCID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM positions WHERE ccid = ?', (ccid,))
            row = cursor.fetchone()
            return self._row_to_position(row) if row else None

    def get_lots_for_position(self, ccid: str, status: str = None) -> List[PositionLot]:
        """Get all lots for a position, optionally filtered by status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if status:
                cursor.execute('''
                    SELECT * FROM position_lots
                    WHERE ccid = ? AND status = ?
                    ORDER BY entry_time ASC
                ''', (ccid, status))
            else:
                cursor.execute('''
                    SELECT * FROM position_lots
                    WHERE ccid = ?
                    ORDER BY entry_time ASC
                ''', (ccid,))

            rows = cursor.fetchall()
            return [self._row_to_lot(row) for row in rows]

    # ==================== ROBINHOOD SYNC ====================

    def sync_from_robinhood(self, trader) -> SyncResult:
        """
        Reconcile local ledger with Robinhood API ground truth.

        This method:
        1. Fetches all open positions from Robinhood
        2. Creates/updates local positions to match
        3. Marks local positions as orphaned if not in Robinhood

        Args:
            trader: Trader instance with get_open_option_positions() method

        Returns:
            SyncResult with counts of added/updated/orphaned positions
        """
        result = SyncResult(
            positions_added=0,
            positions_updated=0,
            positions_orphaned=0,
            errors=[]
        )

        now = datetime.now().isoformat()

        try:
            # Get positions from Robinhood (outside lock to avoid holding lock during API call)
            rh_positions = trader.get_open_option_positions()
            logger.info(f"Syncing with Robinhood: {len(rh_positions)} positions found")

            # Collect instrument data for all positions (API calls outside lock)
            position_data = []
            for pos in rh_positions:
                try:
                    instrument_url = pos.get('option')
                    if not instrument_url:
                        result.errors.append(f"Position missing option URL: {pos}")
                        continue

                    instrument = trader.get_option_instrument_data(instrument_url)
                    if not instrument:
                        result.errors.append(f"Failed to fetch instrument for {instrument_url}")
                        continue

                    ticker = get_trader_symbol(pos.get('chain_symbol', '').upper())
                    strike = float(instrument.get('strike_price', 0))
                    option_type = instrument.get('type', 'call')
                    expiration = instrument.get('expiration_date', '')
                    quantity = int(float(pos.get('quantity', 0)))
                    avg_price = float(pos.get('average_price', 0))

                    if not all([ticker, strike, expiration, quantity > 0]):
                        result.errors.append(f"Incomplete position data: {pos}")
                        continue

                    ccid = self.generate_ccid(ticker, expiration, strike, option_type)
                    position_data.append({
                        'ccid': ccid,
                        'ticker': ticker,
                        'strike': strike,
                        'option_type': option_type,
                        'expiration': expiration,
                        'quantity': quantity,
                        'avg_price': avg_price
                    })

                except Exception as e:
                    result.errors.append(f"Error processing position: {e}")
                    logger.error(f"Sync error for position: {e}")

            # Now perform all database operations atomically with lock
            with self.lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    seen_ccids = set()

                    for data in position_data:
                        ccid = data['ccid']
                        seen_ccids.add(ccid)

                        # Check if position exists in ledger
                        cursor.execute('SELECT * FROM positions WHERE ccid = ?', (ccid,))
                        existing = cursor.fetchone()

                        if existing:
                            # Update if quantity differs
                            if existing['total_quantity'] != data['quantity']:
                                cursor.execute('''
                                    UPDATE positions
                                    SET total_quantity = ?,
                                        avg_cost_basis = ?,
                                        status = 'open',
                                        last_update_time = ?
                                    WHERE ccid = ?
                                ''', (data['quantity'], data['avg_price'], now, ccid))
                                result.positions_updated += 1
                                logger.info(f"Updated position {ccid}: qty {existing['total_quantity']} -> {data['quantity']}")
                        else:
                            # Create new position (opened outside bot)
                            cursor.execute('''
                                INSERT INTO positions
                                (ccid, ticker, strike, option_type, expiration, total_quantity,
                                 avg_cost_basis, status, channel, first_entry_time, last_update_time)
                                VALUES (?, ?, ?, ?, ?, ?, ?, 'open', 'manual', ?, ?)
                            ''', (ccid, data['ticker'], data['strike'], data['option_type'],
                                  data['expiration'], data['quantity'], data['avg_price'], now, now))

                            # Create a lot record
                            lot_id = self.generate_lot_id()
                            cursor.execute('''
                                INSERT INTO position_lots
                                (ccid, lot_id, quantity, cost_basis, entry_time, source_trade_id, status)
                                VALUES (?, ?, ?, ?, ?, NULL, 'open')
                            ''', (ccid, lot_id, data['quantity'], data['avg_price'], now))

                            result.positions_added += 1
                            logger.info(f"Added position from Robinhood {ccid}: {data['quantity']} @ ${data['avg_price']:.2f}")

                    # Mark orphaned positions (in ledger but not in Robinhood)
                    cursor.execute("SELECT ccid FROM positions WHERE status = 'open'")
                    local_open = {row['ccid'] for row in cursor.fetchall()}

                    orphaned = local_open - seen_ccids
                    for ccid in orphaned:
                        cursor.execute('''
                            UPDATE positions
                            SET status = 'closed',
                                notes = COALESCE(notes, '') || ' [Orphaned during sync ' || ? || ']',
                                last_update_time = ?
                            WHERE ccid = ?
                        ''', (now, now, ccid))
                        result.positions_orphaned += 1
                        logger.warning(f"Orphaned position {ccid} - not found in Robinhood")

            logger.info(f"Sync complete: added={result.positions_added}, "
                       f"updated={result.positions_updated}, orphaned={result.positions_orphaned}")

        except Exception as e:
            result.errors.append(f"Sync failed: {e}")
            logger.error(f"Robinhood sync failed: {e}")

        return result

    # ==================== POSITION RESOLUTION ====================

    def resolve_position(
        self,
        ticker: str,
        hints: Optional[Dict[str, Any]] = None,
        heuristic: str = LEDGER_HEURISTIC_STRATEGY,
        return_all: bool = False
    ) -> Union[Optional[Position], List[Position]]:
        """
        Resolve a ticker to specific position(s) using hints and heuristics.

        This is the key method for handling generic alerts like "Trim SPY".

        Args:
            ticker: The ticker symbol (handles variants like SPX/SPXW)
            hints: Optional dict with known contract details:
                - strike: float (exact strike price)
                - type/option_type: str ('call' or 'put')
                - expiry/expiration: str (date in various formats)
                - exit_all: bool (if True, returns all matching positions)
            heuristic: Strategy when multiple matches exist:
                - 'fifo': First In First Out (oldest first) [default]
                - 'nearest': Nearest expiration first (0DTE priority)
                - 'profit': Highest unrealized profit % first (requires market data)
                - 'largest': Largest position (by quantity) first
            return_all: If True, return all matching positions (for "exit all")

        Returns:
            Single Position, list of Positions (if return_all), or None
        """
        hints = hints or {}

        # Check for exit_all flag
        if hints.get('exit_all'):
            return_all = True

        # Get all open positions for this ticker
        positions = self.get_open_positions(ticker)

        if not positions:
            logger.debug(f"No open positions found for {ticker}")
            return [] if return_all else None

        if len(positions) == 1 and not return_all:
            logger.debug(f"Single position found for {ticker}: {positions[0].ccid}")
            return positions[0]

        # Apply weighted matching to score candidates
        scored_positions = []
        for pos in positions:
            score = self._calculate_match_score(pos, hints)
            scored_positions.append((score, pos))

        # Sort by score descending
        scored_positions.sort(key=lambda x: x[0], reverse=True)

        # Log scoring results
        logger.debug(f"Position scoring for {ticker}:")
        for score, pos in scored_positions:
            logger.debug(f"  {pos.ccid}: score={score}")

        if return_all:
            # Return all positions, ordered by score
            return [pos for _, pos in scored_positions]

        # Check if we have a clear winner (score significantly higher)
        if len(scored_positions) >= 2:
            top_score = scored_positions[0][0]
            second_score = scored_positions[1][0]

            if top_score > second_score:
                # Clear winner based on hints
                winner = scored_positions[0][1]
                logger.info(f"Resolved {ticker} to {winner.ccid} (score: {top_score} vs {second_score})")
                return winner

        # Scores are tied or no hints provided - apply heuristic
        tied_positions = [pos for score, pos in scored_positions
                         if score == scored_positions[0][0]]

        result = self._apply_heuristic(tied_positions, heuristic)
        logger.info(f"Applied '{heuristic}' heuristic for {ticker}: selected {result.ccid}")
        return result

    def _calculate_match_score(self, position: Position, hints: Dict[str, Any]) -> int:
        """
        Calculate match score for a position based on hints.

        Scoring:
        - Exact strike match: +10
        - Exact expiry match: +10
        - Option type match: +5
        - 0DTE bonus (if expiring today): +3
        """
        score = 0

        # Strike match
        hint_strike = hints.get('strike')
        if hint_strike is not None:
            if abs(float(hint_strike) - position.strike) < 0.01:
                score += 10

        # Expiration match
        hint_expiry = hints.get('expiry') or hints.get('expiration')
        if hint_expiry:
            # Normalize expiration formats
            hint_date = self._normalize_date(hint_expiry)
            pos_date = self._normalize_date(position.expiration)
            if hint_date and pos_date and hint_date == pos_date:
                score += 10

        # Option type match
        hint_type = hints.get('type') or hints.get('option_type')
        if hint_type:
            hint_type_normalized = 'call' if hint_type.lower() in ('call', 'c') else 'put'
            if position.option_type.lower() == hint_type_normalized:
                score += 5

        # 0DTE bonus
        today = date.today().isoformat()
        if position.expiration == today:
            score += 3

        return score

    def _normalize_date(self, date_str: str) -> Optional[str]:
        """Normalize various date formats to YYYY-MM-DD."""
        if not date_str:
            return None

        # Handle special cases
        date_str = str(date_str).strip().lower()

        if date_str in ('0dte', '0-dte', 'today'):
            return date.today().isoformat()

        # Try various formats
        formats = ['%Y-%m-%d', '%Y%m%d', '%m/%d/%Y', '%m/%d/%y', '%m-%d-%Y']
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date().isoformat()
            except ValueError:
                continue

        return None

    def _apply_heuristic(self, positions: List[Position], heuristic: str) -> Position:
        """
        Apply heuristic to select from tied positions.

        Heuristics:
        - fifo: First In First Out (oldest entry time)
        - nearest: Nearest expiration (0DTE priority)
        - profit: Highest profit % (would need market data - falls back to fifo)
        - largest: Largest position by quantity
        """
        if not positions:
            raise ValueError("No positions to apply heuristic to")

        if len(positions) == 1:
            return positions[0]

        if heuristic == 'fifo':
            # Oldest first (by first_entry_time)
            return min(positions, key=lambda p: p.first_entry_time)

        elif heuristic == 'nearest':
            # Nearest expiration first (0DTE priority)
            today = date.today().isoformat()

            # Separate 0DTE from others
            zero_dte = [p for p in positions if p.expiration == today]
            if zero_dte:
                # Among 0DTE, use FIFO
                return min(zero_dte, key=lambda p: p.first_entry_time)

            # Otherwise, sort by expiration
            return min(positions, key=lambda p: p.expiration)

        elif heuristic == 'profit':
            # Would need market data to calculate unrealized P&L
            # For now, fall back to FIFO
            logger.debug("Profit heuristic not implemented, falling back to FIFO")
            return min(positions, key=lambda p: p.first_entry_time)

        elif heuristic == 'largest':
            # Largest position by quantity
            return max(positions, key=lambda p: p.total_quantity)

        else:
            # Unknown heuristic, default to FIFO
            logger.warning(f"Unknown heuristic '{heuristic}', defaulting to FIFO")
            return min(positions, key=lambda p: p.first_entry_time)

    # ==================== LOCK MECHANISM ====================

    def lock_for_exit(self, ccid: str, timeout_seconds: int = 60) -> bool:
        """
        Lock a position to prevent concurrent sell attempts.

        Sets status to 'pending_exit' with timestamp. The lock automatically
        expires after timeout_seconds if not released.

        Args:
            ccid: Canonical Contract ID to lock
            timeout_seconds: Lock timeout in seconds (default 60)

        Returns:
            True if lock acquired, False if already locked or position not found
        """
        with self.lock:
            now = datetime.now()

            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Get current position
                cursor.execute('SELECT * FROM positions WHERE ccid = ?', (ccid,))
                position = cursor.fetchone()

                if not position:
                    logger.error(f"Cannot lock - position not found: {ccid}")
                    return False

                if position['status'] == 'pending_exit':
                    # Check if lock has expired
                    if position['pending_exit_since']:
                        lock_time = datetime.fromisoformat(position['pending_exit_since'])
                        if (now - lock_time).total_seconds() < timeout_seconds:
                            logger.warning(f"Position {ccid} already locked for exit")
                            return False
                        else:
                            logger.info(f"Lock expired for {ccid}, re-acquiring")

                # Acquire lock
                cursor.execute('''
                    UPDATE positions
                    SET status = 'pending_exit',
                        pending_exit_since = ?,
                        last_update_time = ?
                    WHERE ccid = ?
                ''', (now.isoformat(), now.isoformat(), ccid))

                logger.info(f"Locked position {ccid} for exit")
                return True

    def unlock_position(self, ccid: str) -> bool:
        """
        Release lock on a position (e.g., if sell failed).

        Args:
            ccid: Canonical Contract ID to unlock

        Returns:
            True if unlocked, False if position not found
        """
        with self.lock:
            now = datetime.now().isoformat()

            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    UPDATE positions
                    SET status = 'open',
                        pending_exit_since = NULL,
                        last_update_time = ?
                    WHERE ccid = ? AND status = 'pending_exit'
                ''', (now, ccid))

                if cursor.rowcount > 0:
                    logger.info(f"Unlocked position {ccid}")
                    return True
                else:
                    logger.warning(f"Could not unlock {ccid} - not in pending_exit status")
                    return False

    def is_locked(self, ccid: str) -> bool:
        """Check if a position is currently locked for exit."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status FROM positions WHERE ccid = ?",
                (ccid,)
            )
            row = cursor.fetchone()
            return row is not None and row['status'] == 'pending_exit'

    def cleanup_expired_locks(self, timeout_seconds: int = 60) -> int:
        """
        Release all expired locks.

        Args:
            timeout_seconds: Lock timeout threshold

        Returns:
            Number of locks released
        """
        now = datetime.now()
        cutoff = (now - timedelta(seconds=timeout_seconds)).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE positions
                SET status = 'open',
                    pending_exit_since = NULL,
                    last_update_time = ?
                WHERE status = 'pending_exit'
                  AND pending_exit_since < ?
            ''', (now.isoformat(), cutoff))

            count = cursor.rowcount
            if count > 0:
                logger.info(f"Released {count} expired locks")
            return count

    # ==================== EXIT ALL TICKER ====================

    def get_all_positions_for_exit(self, ticker: str) -> List[Position]:
        """
        Get all open positions for a ticker for "Exit all" operations.

        Args:
            ticker: The ticker symbol (handles variants)

        Returns:
            List of all open Position objects for this ticker
        """
        return self.resolve_position(ticker, hints={'exit_all': True}, return_all=True)

    def exit_all_positions(self, ticker: str, price: float) -> List[str]:
        """
        Close all positions for a ticker at the specified price.

        Args:
            ticker: The ticker symbol
            price: Exit price per contract

        Returns:
            List of CCIDs that were closed
        """
        positions = self.get_all_positions_for_exit(ticker)
        closed_ccids = []

        for pos in positions:
            try:
                self.record_sell(pos.ccid, pos.total_quantity, price)
                closed_ccids.append(pos.ccid)
                logger.info(f"Closed position {pos.ccid}: {pos.total_quantity} @ ${price:.2f}")
            except Exception as e:
                logger.error(f"Failed to close {pos.ccid}: {e}")

        return closed_ccids

    # ==================== UTILITY METHODS ====================

    def get_position_summary(self) -> dict:
        """Get a summary of all positions in the ledger."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Count by status
            cursor.execute('''
                SELECT status, COUNT(*) as count, SUM(total_quantity) as total_qty
                FROM positions
                GROUP BY status
            ''')
            status_counts = {row['status']: {'count': row['count'], 'quantity': row['total_qty']}
                            for row in cursor.fetchall()}

            # Count unique tickers
            cursor.execute("SELECT COUNT(DISTINCT ticker) as count FROM positions WHERE status = 'open'")
            unique_tickers = cursor.fetchone()['count']

            return {
                'by_status': status_counts,
                'unique_tickers': unique_tickers,
                'open_positions': status_counts.get('open', {}).get('count', 0),
                'total_open_contracts': status_counts.get('open', {}).get('quantity', 0)
            }

    def __repr__(self) -> str:
        summary = self.get_position_summary()
        return (f"PositionLedger(db={self.db_path}, "
                f"open={summary['open_positions']}, "
                f"contracts={summary['total_open_contracts']})")
