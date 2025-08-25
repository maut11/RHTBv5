# position_manager.py - Enhanced Position Manager with Symbol Mapping
import json
import os
from threading import Lock
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from config import get_broker_symbol, get_trader_symbol, get_all_symbol_variants, SYMBOL_NORMALIZATION_CONFIG

class EnhancedPositionManager:
    """
    Enhanced position manager with strict channel isolation and symbol mapping.
    Each channel maintains completely separate position lists.
    Handles both trader symbols (SPX) and broker symbols (SPXW).
    """
    
    def __init__(self, track_file: str):
        self.track_file = track_file
        self._lock = Lock()
        # Structure: {channel_id: [list of positions]}
        self._positions = self._load()
        self._migrate_positions_if_needed()
        print(f"✅ Enhanced Position Manager initialized with symbol mapping: {track_file}")

    def _load(self) -> dict:
        """Load positions from file with error handling"""
        if os.path.exists(self.track_file):
            try:
                with open(self.track_file, 'r') as f:
                    data = json.load(f)
                    print(f"📂 Loaded {sum(len(positions) for positions in data.values())} positions across {len(data)} channels")
                    return data
            except json.JSONDecodeError as e:
                print(f"❌ Error loading position file: {e}. Starting fresh.")
                return {}
            except Exception as e:
                print(f"❌ Unexpected error loading positions: {e}")
                return {}
        return {}

    def _migrate_positions_if_needed(self):
        """Migrate existing positions to include both trader and broker symbols"""
        with self._lock:
            migrated = False
            for channel_id, positions in self._positions.items():
                for position in positions:
                    # Add broker_symbol if not present
                    if 'broker_symbol' not in position and 'symbol' in position:
                        trader_symbol = position['symbol']
                        broker_symbol = get_broker_symbol(trader_symbol)
                        position['broker_symbol'] = broker_symbol
                        position['trader_symbol'] = trader_symbol
                        migrated = True
                        
                    # Add trader_symbol if not present but broker_symbol exists
                    elif 'trader_symbol' not in position and 'broker_symbol' in position:
                        broker_symbol = position['broker_symbol']
                        trader_symbol = get_trader_symbol(broker_symbol)
                        position['trader_symbol'] = trader_symbol
                        migrated = True
                    
                    # Ensure we have symbol_variants for quick lookup
                    if 'symbol_variants' not in position:
                        symbol = position.get('symbol') or position.get('trader_symbol')
                        if symbol:
                            position['symbol_variants'] = get_all_symbol_variants(symbol)
                            migrated = True
            
            if migrated:
                self._save()
                print("📊 Migrated positions to include symbol mapping")

    def _save(self):
        """Save positions to file with backup"""
        try:
            # Create backup first
            if os.path.exists(self.track_file):
                backup_file = f"{self.track_file}.backup"
                with open(self.track_file, 'r') as src, open(backup_file, 'w') as dst:
                    dst.write(src.read())
            
            # Save current data
            with open(self.track_file, 'w') as f:
                json.dump(self._positions, f, indent=2)
                
        except Exception as e:
            print(f"❌ Error saving positions: {e}")

    def add_position(self, channel_id: int, trade_data: dict) -> Optional[dict]:
        """
        Add a new position to the specific channel's list with symbol mapping.
        Maintains strict channel isolation.
        """
        channel_id_str = str(channel_id)
        
        trade_id = trade_data.get("trade_id")
        if not trade_id:
            print("❌ PositionManager Error: trade_id was not provided in trade_data.")
            return None

        # Get both trader and broker symbols
        trader_symbol = trade_data.get("ticker") or trade_data.get("symbol")
        broker_symbol = get_broker_symbol(trader_symbol) if trader_symbol else None
        symbol_variants = get_all_symbol_variants(trader_symbol) if trader_symbol else []

        contract_info = {
            "trade_id": trade_id,
            "symbol": trader_symbol,  # Keep original field for compatibility
            "trader_symbol": trader_symbol,
            "broker_symbol": broker_symbol,
            "symbol_variants": symbol_variants,
            "strike": trade_data.get("strike"),
            "type": trade_data.get("type"),
            "expiration": trade_data.get("expiration"),
            "purchase_price": trade_data.get("price"),
            "entry_price": trade_data.get("price"),  # Store as both for compatibility
            "size": trade_data.get("size", "full"),
            "quantity": trade_data.get("quantity", 1),
            "channel": trade_data.get("channel"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "open"
        }
        
        # Filter out None values
        contract_info = {k: v for k, v in contract_info.items() if v is not None}

        with self._lock:
            if channel_id_str not in self._positions:
                self._positions[channel_id_str] = []
            
            # Check for duplicate trade_id in this channel
            existing_trade_ids = [pos.get("trade_id") for pos in self._positions[channel_id_str]]
            if trade_id in existing_trade_ids:
                print(f"⚠️ Trade ID {trade_id} already exists in channel {channel_id_str}")
                return None
            
            self._positions[channel_id_str].append(contract_info)
            self._save()
            
        print(f"✅ Position added to channel {channel_id_str}: {trader_symbol} (broker: {broker_symbol}) (Trade ID: {trade_id})")
        if SYMBOL_NORMALIZATION_CONFIG.get('log_conversions') and trader_symbol != broker_symbol:
            print(f"   Symbol mapping: {trader_symbol} → {broker_symbol}")
        
        return contract_info

    def find_position(self, channel_id: int, trade_data: dict) -> Optional[dict]:
        """
        Find a specific position within a channel with symbol mapping support.
        STRICT channel isolation - only looks within the specified channel.
        """
        channel_id_str = str(channel_id)
        
        with self._lock:
            active_trades = self._positions.get(channel_id_str, [])
            if not active_trades:
                return None

            ticker = trade_data.get("ticker") or trade_data.get("symbol")
            trade_id = trade_data.get("trade_id")
            
            # Get all symbol variants for searching
            symbol_variants = get_all_symbol_variants(ticker) if ticker else []
            
            # Strategy 1: Exact trade_id match (most precise)
            if trade_id:
                for trade in active_trades:
                    if trade.get("trade_id") == trade_id and trade.get("status") == "open":
                        print(f"🎯 Found position by trade_id in channel {channel_id_str}: {trade_id}")
                        return trade
            
            # Strategy 2: Symbol match with variants - find most recent open position
            if ticker and symbol_variants:
                matching_trades = []
                for trade in active_trades:
                    if trade.get("status") == "open":
                        # Check if any of the position's symbols match our search variants
                        position_symbols = [
                            trade.get("symbol"),
                            trade.get("trader_symbol"),
                            trade.get("broker_symbol")
                        ]
                        position_symbols = [s.upper() for s in position_symbols if s]
                        
                        # Also check stored variants
                        if trade.get("symbol_variants"):
                            position_symbols.extend([v.upper() for v in trade.get("symbol_variants", [])])
                        
                        # Check for match
                        if any(variant in position_symbols for variant in symbol_variants):
                            matching_trades.append(trade)
                
                if matching_trades:
                    # Return the most recently created position
                    most_recent = max(matching_trades, key=lambda x: x.get("created_at", ""))
                    found_symbol = most_recent.get("trader_symbol") or most_recent.get("symbol")
                    print(f"📍 Found position by symbol variants in channel {channel_id_str}: {ticker} → {found_symbol} (Trade ID: {most_recent.get('trade_id')})")
                    if ticker != found_symbol:
                        print(f"   Symbol variant match: {ticker} matched with {found_symbol}")
                    return most_recent
            
            # Strategy 3: No identifying info - return most recent open position
            open_trades = [trade for trade in active_trades if trade.get("status") == "open"]
            if open_trades:
                most_recent = max(open_trades, key=lambda x: x.get("created_at", ""))
                print(f"🔍 Found most recent position in channel {channel_id_str}: {most_recent.get('trader_symbol')} (Trade ID: {most_recent.get('trade_id')})")
                return most_recent
            
            return None

    def find_position_by_ticker(self, channel_id: int, ticker: str) -> Optional[dict]:
        """
        Find the most recent open position for a specific ticker within a channel.
        Handles symbol mapping (SPX/SPXW).
        """
        channel_id_str = str(channel_id)
        
        with self._lock:
            active_trades = self._positions.get(channel_id_str, [])
            
            # Get all symbol variants for searching
            symbol_variants = get_all_symbol_variants(ticker)
            
            matching_trades = []
            for trade in active_trades:
                if trade.get("status") == "open":
                    # Check all stored symbols
                    position_symbols = [
                        trade.get("symbol"),
                        trade.get("trader_symbol"),
                        trade.get("broker_symbol")
                    ]
                    position_symbols = [s.upper() for s in position_symbols if s]
                    
                    # Also check stored variants
                    if trade.get("symbol_variants"):
                        position_symbols.extend([v.upper() for v in trade.get("symbol_variants", [])])
                    
                    # Check for match
                    if any(variant in position_symbols for variant in symbol_variants):
                        matching_trades.append(trade)
            
            if matching_trades:
                # Return the most recently created position
                most_recent = max(matching_trades, key=lambda x: x.get("created_at", ""))
                found_symbol = most_recent.get("trader_symbol") or most_recent.get("symbol")
                print(f"📍 Found position for {ticker} (variants: {symbol_variants}) in channel {channel_id_str}: {most_recent.get('trade_id')}")
                if ticker != found_symbol:
                    print(f"   Symbol mapping: {ticker} → {found_symbol}")
                return most_recent
            
            return None

    def update_position_status(self, channel_id: int, trade_id: str, status: str, additional_data: dict = None):
        """
        Update position status (e.g., 'trimmed', 'closed') and add additional data.
        """
        channel_id_str = str(channel_id)
        
        with self._lock:
            if channel_id_str in self._positions:
                for trade in self._positions[channel_id_str]:
                    if trade.get("trade_id") == trade_id:
                        trade["status"] = status
                        trade["updated_at"] = datetime.now(timezone.utc).isoformat()
                        
                        if additional_data:
                            trade.update(additional_data)
                        
                        self._save()
                        print(f"📝 Updated position {trade_id} in channel {channel_id_str}: status = {status}")
                        return True
            
            print(f"❌ Position {trade_id} not found in channel {channel_id_str}")
            return False

    def clear_position(self, channel_id: int, trade_id: str):
        """
        Mark position as closed rather than deleting it (for historical tracking).
        """
        channel_id_str = str(channel_id)
        
        with self._lock:
            if channel_id_str in self._positions:
                for trade in self._positions[channel_id_str]:
                    if trade.get("trade_id") == trade_id:
                        trade["status"] = "closed"
                        trade["closed_at"] = datetime.now(timezone.utc).isoformat()
                        self._save()
                        symbol = trade.get("trader_symbol") or trade.get("symbol")
                        print(f"✅ Closed position {trade_id} for {symbol} in channel {channel_id_str}")
                        return True
            
            print(f"❌ Position {trade_id} not found for closing in channel {channel_id_str}")
            return False

    def get_open_positions(self, channel_id: int = None) -> List[dict]:
        """
        Get all open positions for a specific channel or all channels.
        """
        with self._lock:
            if channel_id:
                channel_id_str = str(channel_id)
                positions = self._positions.get(channel_id_str, [])
                return [pos for pos in positions if pos.get("status") == "open"]
            else:
                all_open = []
                for channel_positions in self._positions.values():
                    all_open.extend([pos for pos in channel_positions if pos.get("status") == "open"])
                return all_open

    def get_channel_summary(self, channel_id: int) -> dict:
        """
        Get summary statistics for a specific channel.
        """
        channel_id_str = str(channel_id)
        
        with self._lock:
            positions = self._positions.get(channel_id_str, [])
            
            open_positions = [pos for pos in positions if pos.get("status") == "open"]
            closed_positions = [pos for pos in positions if pos.get("status") == "closed"]
            
            # Get unique tickers including mapped symbols
            open_tickers = set()
            for pos in open_positions:
                if pos.get("trader_symbol"):
                    open_tickers.add(pos.get("trader_symbol"))
                elif pos.get("symbol"):
                    open_tickers.add(pos.get("symbol"))
            
            return {
                "channel_id": channel_id,
                "total_positions": len(positions),
                "open_positions": len(open_positions),
                "closed_positions": len(closed_positions),
                "open_tickers": list(open_tickers),
                "recent_activity": sorted(positions, key=lambda x: x.get("created_at", ""))[-5:]
            }

    def get_all_channels_summary(self) -> dict:
        """
        Get summary for all channels.
        """
        with self._lock:
            summary = {}
            for channel_id_str in self._positions.keys():
                channel_id = int(channel_id_str)
                summary[channel_id_str] = self.get_channel_summary(channel_id)
            
            return summary

    def cleanup_old_positions(self, days_old: int = 30):
        """
        Clean up very old closed positions to keep file size manageable.
        """
        from datetime import timedelta
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)
        cutoff_str = cutoff_date.isoformat()
        
        with self._lock:
            cleaned_count = 0
            for channel_id_str in self._positions:
                original_count = len(self._positions[channel_id_str])
                
                # Keep open positions and recent closed positions
                self._positions[channel_id_str] = [
                    pos for pos in self._positions[channel_id_str]
                    if (pos.get("status") == "open" or 
                        pos.get("closed_at", "9999-12-31") > cutoff_str)
                ]
                
                cleaned_count += original_count - len(self._positions[channel_id_str])
            
            if cleaned_count > 0:
                self._save()
                print(f"🧹 Cleaned up {cleaned_count} old positions (older than {days_old} days)")
            
            return cleaned_count

    def find_position_by_contract_details(self, channel_id: int, symbol: str, strike: float, 
                                         expiration: str, opt_type: str) -> Optional[dict]:
        """
        Find position by exact contract details with symbol mapping support.
        """
        channel_id_str = str(channel_id)
        
        with self._lock:
            active_trades = self._positions.get(channel_id_str, [])
            
            # Get all symbol variants
            symbol_variants = get_all_symbol_variants(symbol)
            
            for trade in active_trades:
                if trade.get("status") != "open":
                    continue
                
                # Check symbol match with variants
                position_symbols = [
                    trade.get("symbol"),
                    trade.get("trader_symbol"),
                    trade.get("broker_symbol")
                ]
                position_symbols = [s.upper() for s in position_symbols if s]
                
                symbol_match = any(variant in position_symbols for variant in symbol_variants)
                
                # Check other contract details
                strike_match = abs(float(trade.get("strike", 0)) - float(strike)) < 0.01
                exp_match = trade.get("expiration") == str(expiration)
                type_match = trade.get("type", "").lower() == str(opt_type).lower()
                
                if symbol_match and strike_match and exp_match and type_match:
                    print(f"✅ Found exact contract match in channel {channel_id_str}: {trade.get('trade_id')}")
                    return trade
            
            return None

    def export_positions_csv(self, filename: str = None):
        """
        Export all positions to CSV for analysis.
        """
        import csv
        
        if not filename:
            filename = f"positions_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        with self._lock:
            all_positions = []
            for channel_id_str, positions in self._positions.items():
                for pos in positions:
                    pos_copy = pos.copy()
                    pos_copy["channel_id"] = channel_id_str
                    all_positions.append(pos_copy)
            
            if not all_positions:
                print("📊 No positions to export")
                return
            
            # Get all unique keys for CSV headers
            all_keys = set()
            for pos in all_positions:
                all_keys.update(pos.keys())
            
            fieldnames = sorted(all_keys)
            
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for pos in all_positions:
                    writer.writerow(pos)
            
            print(f"📊 Exported {len(all_positions)} positions to {filename}")

    def debug_positions(self, channel_id: int = None):
        """
        Debug method to print current positions with symbol mapping details.
        """
        with self._lock:
            if channel_id:
                channel_id_str = str(channel_id)
                positions = self._positions.get(channel_id_str, [])
                print(f"\n🔍 Debug: Positions for channel {channel_id_str}:")
            else:
                print(f"\n🔍 Debug: All positions:")
                positions = []
                for ch_id, ch_positions in self._positions.items():
                    for pos in ch_positions:
                        pos_copy = pos.copy()
                        pos_copy['_channel'] = ch_id
                        positions.append(pos_copy)
            
            for pos in positions:
                if pos.get("status") == "open":
                    print(f"  Trade ID: {pos.get('trade_id')}")
                    print(f"    Trader Symbol: {pos.get('trader_symbol')}")
                    print(f"    Broker Symbol: {pos.get('broker_symbol')}")
                    print(f"    Variants: {pos.get('symbol_variants')}")
                    print(f"    Contract: ${pos.get('strike')} {pos.get('type')} {pos.get('expiration')}")
                    print(f"    Entry Price: ${pos.get('entry_price')}")
                    print(f"    Status: {pos.get('status')}")
                    if '_channel' in pos:
                        print(f"    Channel: {pos['_channel']}")
                    print()

# Compatibility alias
PositionManager = EnhancedPositionManager

# Export
__all__ = ['EnhancedPositionManager', 'PositionManager']