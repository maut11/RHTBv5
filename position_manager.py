# position_manager.py - Enhanced Position Manager with Channel Isolation
import json
import os
from threading import Lock
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

class EnhancedPositionManager:
    """
    Enhanced position manager with strict channel isolation and better tracking.
    Each channel maintains completely separate position lists.
    """
    
    def __init__(self, track_file: str):
        self.track_file = track_file
        self._lock = Lock()
        # Structure: {channel_id: [list of positions]}
        self._positions = self._load()
        print(f"✅ Enhanced Position Manager initialized: {track_file}")

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
        Add a new position to the specific channel's list.
        Maintains strict channel isolation.
        """
        channel_id_str = str(channel_id)
        
        trade_id = trade_data.get("trade_id")
        if not trade_id:
            print("❌ PositionManager Error: trade_id was not provided in trade_data.")
            return None

        contract_info = {
            "trade_id": trade_id,
            "symbol": trade_data.get("ticker"),
            "strike": trade_data.get("strike"),
            "type": trade_data.get("type"),
            "expiration": trade_data.get("expiration"),
            "purchase_price": trade_data.get("price"),
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
            
        print(f"✅ Position added to channel {channel_id_str}: {contract_info.get('symbol')} (Trade ID: {trade_id})")
        return contract_info

    def find_position(self, channel_id: int, trade_data: dict) -> Optional[dict]:
        """
        Find a specific position within a channel with multiple lookup strategies.
        STRICT channel isolation - only looks within the specified channel.
        """
        channel_id_str = str(channel_id)
        
        with self._lock:
            active_trades = self._positions.get(channel_id_str, [])
            if not active_trades:
                return None

            ticker = trade_data.get("ticker")
            trade_id = trade_data.get("trade_id")
            
            # Strategy 1: Exact trade_id match (most precise)
            if trade_id:
                for trade in active_trades:
                    if trade.get("trade_id") == trade_id and trade.get("status") == "open":
                        print(f"🎯 Found position by trade_id in channel {channel_id_str}: {trade_id}")
                        return trade
            
            # Strategy 2: Ticker match - find most recent open position for this ticker
            if ticker:
                matching_trades = [
                    trade for trade in active_trades 
                    if trade.get("symbol") == ticker and trade.get("status") == "open"
                ]
                if matching_trades:
                    # Return the most recently created position
                    most_recent = max(matching_trades, key=lambda x: x.get("created_at", ""))
                    print(f"📍 Found position by ticker in channel {channel_id_str}: {ticker} (Trade ID: {most_recent.get('trade_id')})")
                    return most_recent
            
            # Strategy 3: No identifying info - return most recent open position
            open_trades = [trade for trade in active_trades if trade.get("status") == "open"]
            if open_trades:
                most_recent = max(open_trades, key=lambda x: x.get("created_at", ""))
                print(f"🔍 Found most recent position in channel {channel_id_str}: {most_recent.get('symbol')} (Trade ID: {most_recent.get('trade_id')})")
                return most_recent
            
            return None

    def find_position_by_ticker(self, channel_id: int, ticker: str) -> Optional[dict]:
        """
        Find the most recent open position for a specific ticker within a channel.
        """
        channel_id_str = str(channel_id)
        
        with self._lock:
            active_trades = self._positions.get(channel_id_str, [])
            matching_trades = [
                trade for trade in active_trades 
                if trade.get("symbol") == ticker and trade.get("status") == "open"
            ]
            
            if matching_trades:
                # Return the most recently created position
                most_recent = max(matching_trades, key=lambda x: x.get("created_at", ""))
                print(f"📍 Found position for {ticker} in channel {channel_id_str}: {most_recent.get('trade_id')}")
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
                        print(f"✅ Closed position {trade_id} in channel {channel_id_str}")
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
            
            return {
                "channel_id": channel_id,
                "total_positions": len(positions),
                "open_positions": len(open_positions),
                "closed_positions": len(closed_positions),
                "open_tickers": list(set(pos.get("symbol") for pos in open_positions)),
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