"""
Unified CSV Trade Tracking System
Comprehensive trade logging with latency metrics and performance tracking
"""
import csv
import threading
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import uuid


@dataclass
class TradeRecord:
    """Complete trade record with all required fields"""
    date: str
    time: str
    channel: str
    alert_type: str
    ticker: str
    strike: Optional[str]
    expiration: Optional[str]
    trade_id: str
    parent_trade_id: Optional[str]
    alerted_price: Optional[float]
    executed_price: Optional[float]
    contracts: Optional[int]
    sell_alert_price: Optional[float]
    sell_executed_price: Optional[float]
    pnl_percent: Optional[float]
    is_reactive: bool
    target_level: Optional[str]
    parse_latency_ms: Optional[float]
    validate_latency_ms: Optional[float]
    execute_latency_ms: Optional[float]
    setup_latency_ms: Optional[float]
    confirm_latency_ms: Optional[float]
    total_processing_time_ms: Optional[float]
    status: str
    notes: Optional[str]
    
    @classmethod
    def from_trade_data(cls, trade_data: Dict, latency_breakdown: Dict = None) -> 'TradeRecord':
        """Create TradeRecord from trade data and latency breakdown"""
        now = datetime.now()
        latency = latency_breakdown or {}
        
        return cls(
            date=now.strftime('%Y-%m-%d'),
            time=now.strftime('%H:%M:%S'),
            channel=trade_data.get('channel', ''),
            alert_type=trade_data.get('action', ''),
            ticker=trade_data.get('ticker', ''),
            strike=str(trade_data.get('strike', '')) if trade_data.get('strike') else None,
            expiration=trade_data.get('expiration', ''),
            trade_id=trade_data.get('trade_id', str(uuid.uuid4())),
            parent_trade_id=trade_data.get('parent_trade_id'),
            alerted_price=trade_data.get('price'),
            executed_price=trade_data.get('executed_price'),
            contracts=trade_data.get('size', 1),
            sell_alert_price=None,  # Will be updated on exit/trim
            sell_executed_price=None,  # Will be updated on exit/trim
            pnl_percent=None,  # Will be calculated on exit
            is_reactive=trade_data.get('is_reactive', False),
            target_level=trade_data.get('target_level'),
            parse_latency_ms=latency.get('parse_latency_ms'),
            validate_latency_ms=latency.get('validate_latency_ms'),
            execute_latency_ms=latency.get('execute_latency_ms'),
            setup_latency_ms=latency.get('setup_latency_ms'),
            confirm_latency_ms=latency.get('confirm_latency_ms'),
            total_processing_time_ms=latency.get('total_processing_time_ms'),
            status=trade_data.get('status', 'pending'),
            notes=trade_data.get('notes', '')
        )


class UnifiedCSVTracker:
    """
    Thread-safe unified CSV tracking system for all trade activity
    """
    
    # CSV headers matching the required structure
    CSV_HEADERS = [
        'date', 'time', 'channel', 'alert_type', 'ticker', 'strike', 'expiration',
        'trade_id', 'parent_trade_id', 'alerted_price', 'executed_price', 'contracts',
        'sell_alert_price', 'sell_executed_price', 'pnl_percent', 'is_reactive',
        'target_level', 'parse_latency_ms', 'validate_latency_ms', 'execute_latency_ms',
        'setup_latency_ms', 'confirm_latency_ms', 'total_processing_time_ms', 'status', 'notes'
    ]
    
    def __init__(self, csv_dir: str = "trade_logs"):
        self.csv_dir = Path(csv_dir)
        self.csv_dir.mkdir(exist_ok=True, parents=True)
        self._lock = threading.RLock()
        self.active_trades: Dict[str, TradeRecord] = {}
        
        # Initialize daily CSV file
        self._ensure_daily_csv()
    
    def _ensure_daily_csv(self):
        """Ensure today's CSV file exists with headers"""
        today = date.today().strftime('%Y-%m-%d')
        self.current_csv_file = self.csv_dir / f"{today}_trades.csv"
        
        # Create file with headers if it doesn't exist
        if not self.current_csv_file.exists():
            with open(self.current_csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(self.CSV_HEADERS)
    
    def _append_to_csv(self, record: TradeRecord):
        """Append a record to the current CSV file"""
        # Check if we need to rotate to a new day's file
        today = date.today().strftime('%Y-%m-%d')
        expected_file = self.csv_dir / f"{today}_trades.csv"
        
        if expected_file != self.current_csv_file:
            self._ensure_daily_csv()
        
        # Convert record to row
        row_data = []
        for header in self.CSV_HEADERS:
            value = getattr(record, header, '')
            # Handle None values and formatting
            if value is None:
                row_data.append('')
            elif isinstance(value, float):
                row_data.append(f"{value:.4f}" if value != 0 else "0")
            elif isinstance(value, bool):
                row_data.append(str(value).lower())
            else:
                row_data.append(str(value))
        
        # Write to CSV
        with open(self.current_csv_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(row_data)
    
    def record_entry(self, trade_data: Dict, latency_breakdown: Dict = None) -> str:
        """
        Record a new trade entry
        
        Args:
            trade_data: Trade information
            latency_breakdown: Latency metrics from LatencyTracker
            
        Returns:
            str: Trade ID
        """
        with self._lock:
            record = TradeRecord.from_trade_data(trade_data, latency_breakdown)
            
            # Store active trade for future updates
            self.active_trades[record.trade_id] = record
            
            # Write to CSV
            self._append_to_csv(record)
            
            return record.trade_id
    
    def record_trim(self, trade_id: str, trim_data: Dict, latency_breakdown: Dict = None) -> bool:
        """
        Record a trim operation
        
        Args:
            trade_id: Parent trade ID
            trim_data: Trim information
            latency_breakdown: Latency metrics
            
        Returns:
            bool: Success status
        """
        with self._lock:
            parent_trade = self.active_trades.get(trade_id)
            if not parent_trade:
                return False
            
            # Create new record for the trim
            trim_record_data = {
                'channel': parent_trade.channel,
                'action': 'trim',
                'ticker': parent_trade.ticker,
                'strike': parent_trade.strike,
                'expiration': parent_trade.expiration,
                'trade_id': str(uuid.uuid4()),
                'parent_trade_id': trade_id,
                'price': trim_data.get('trim_price'),
                'executed_price': trim_data.get('executed_price'),
                'size': trim_data.get('contracts', 0),
                'status': 'completed',
                'notes': f"Trim of {trim_data.get('contracts', 0)} contracts"
            }
            
            trim_record = TradeRecord.from_trade_data(trim_record_data, latency_breakdown)
            trim_record.sell_alert_price = trim_data.get('trim_price')
            trim_record.sell_executed_price = trim_data.get('executed_price')
            
            # Calculate partial PnL for trim
            if (parent_trade.executed_price and trim_record.sell_executed_price and 
                trim_data.get('contracts', 0) > 0):
                entry_cost = parent_trade.executed_price * trim_data.get('contracts', 0) * 100
                exit_value = trim_record.sell_executed_price * trim_data.get('contracts', 0) * 100
                trim_record.pnl_percent = ((exit_value - entry_cost) / entry_cost) * 100
            
            self._append_to_csv(trim_record)
            return True
    
    def record_exit(self, trade_id: str, exit_data: Dict, latency_breakdown: Dict = None) -> bool:
        """
        Record a complete exit operation
        
        Args:
            trade_id: Trade ID to exit
            exit_data: Exit information  
            latency_breakdown: Latency metrics
            
        Returns:
            bool: Success status
        """
        with self._lock:
            trade = self.active_trades.get(trade_id)
            if not trade:
                return False
            
            # Update the existing trade record with exit information
            exit_record_data = {
                'channel': trade.channel,
                'action': 'exit',
                'ticker': trade.ticker,
                'strike': trade.strike,
                'expiration': trade.expiration,
                'trade_id': str(uuid.uuid4()),
                'parent_trade_id': trade_id,
                'price': exit_data.get('exit_price'),
                'executed_price': exit_data.get('executed_price'),
                'size': exit_data.get('contracts', trade.contracts),
                'status': 'completed',
                'notes': f"Full exit of position"
            }
            
            exit_record = TradeRecord.from_trade_data(exit_record_data, latency_breakdown)
            exit_record.sell_alert_price = exit_data.get('exit_price')
            exit_record.sell_executed_price = exit_data.get('executed_price')
            
            # Calculate PnL
            if (trade.executed_price and exit_record.sell_executed_price and trade.contracts):
                entry_cost = trade.executed_price * trade.contracts * 100
                exit_value = exit_record.sell_executed_price * trade.contracts * 100
                exit_record.pnl_percent = ((exit_value - entry_cost) / entry_cost) * 100
            
            self._append_to_csv(exit_record)
            
            # Remove from active trades
            self.active_trades.pop(trade_id, None)
            
            return True
    
    def update_trade_status(self, trade_id: str, status: str, notes: str = None):
        """Update trade status and notes"""
        with self._lock:
            trade = self.active_trades.get(trade_id)
            if trade:
                trade.status = status
                if notes:
                    trade.notes = notes
    
    def get_daily_summary(self, target_date: str = None) -> Dict:
        """Get summary statistics for a specific date"""
        if not target_date:
            target_date = date.today().strftime('%Y-%m-%d')
        
        csv_file = self.csv_dir / f"{target_date}_trades.csv"
        if not csv_file.exists():
            return {'date': target_date, 'trades': 0, 'summary': 'No trades recorded'}
        
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            trades = list(reader)
        
        entries = [t for t in trades if t['alert_type'] == 'entry']
        exits = [t for t in trades if t['alert_type'] == 'exit']
        trims = [t for t in trades if t['alert_type'] == 'trim']
        
        # Calculate average latencies
        completed_trades = [t for t in trades if t['total_processing_time_ms']]
        avg_latency = 0
        if completed_trades:
            total_latency = sum(float(t['total_processing_time_ms']) for t in completed_trades)
            avg_latency = total_latency / len(completed_trades)
        
        return {
            'date': target_date,
            'total_trades': len(trades),
            'entries': len(entries),
            'exits': len(exits),
            'trims': len(trims),
            'avg_processing_time_ms': f"{avg_latency:.2f}",
            'csv_file': str(csv_file)
        }
    
    def export_date_range(self, start_date: str, end_date: str, output_file: str):
        """Export trades for a date range to a single CSV file"""
        all_records = []
        
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        current = start
        while current <= end:
            csv_file = self.csv_dir / f"{current.strftime('%Y-%m-%d')}_trades.csv"
            if csv_file.exists():
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    all_records.extend(list(reader))
            current = current.replace(day=current.day + 1)
        
        # Write consolidated file
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            if all_records:
                writer = csv.DictWriter(f, fieldnames=self.CSV_HEADERS)
                writer.writeheader()
                writer.writerows(all_records)


# Global CSV tracker instance
_global_csv_tracker = UnifiedCSVTracker()

def get_csv_tracker() -> UnifiedCSVTracker:
    """Get the global CSV tracker instance"""
    return _global_csv_tracker


if __name__ == "__main__":
    # Test the CSV tracking system
    tracker = get_csv_tracker()
    
    # Test entry record
    trade_data = {
        'channel': 'Ryan',
        'action': 'entry',
        'ticker': 'SPX',
        'strike': '5800',
        'expiration': '2025-09-11',
        'price': 10.50,
        'executed_price': 10.45,
        'size': 2,
        'status': 'filled'
    }
    
    latency_data = {
        'parse_latency_ms': 0.5,
        'validate_latency_ms': 2.1,
        'execute_latency_ms': 156.7,
        'setup_latency_ms': 1.2,
        'confirm_latency_ms': 0.8,
        'total_processing_time_ms': 161.3
    }
    
    trade_id = tracker.record_entry(trade_data, latency_data)
    print(f"Recorded entry: {trade_id}")
    
    # Test trim record
    trim_data = {
        'trim_price': 15.00,
        'executed_price': 14.95,
        'contracts': 1
    }
    
    success = tracker.record_trim(trade_id, trim_data, latency_data)
    print(f"Recorded trim: {success}")
    
    # Test daily summary
    summary = tracker.get_daily_summary()
    print(f"Daily summary: {summary}")
    
    print("CSV tracking test complete")
