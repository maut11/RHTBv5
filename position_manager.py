# position_manager.py
import json
import os
from threading import Lock

class PositionManager:
    """
    A thread-safe class to manage and persist the state of multiple open trades 
    across all channels. It can track several simultaneous positions per channel.
    """
    def __init__(self, track_file: str):
        self.track_file = track_file
        self._lock = Lock()
        # _positions now stores a dictionary where each channel ID maps to a LIST of trades.
        self._positions = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.track_file):
            with open(self.track_file, 'r') as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return {}
        return {}

    def _save(self):
        with open(self.track_file, 'w') as f:
            json.dump(self._positions, f, indent=2)

    def add_position(self, channel_id: int, trade_data: dict):
        """
        Adds a new position to the list for a given channel.
        Uses the trade_id provided in trade_data instead of creating a new one.
        """
        channel_id_str = str(channel_id)
        
        # --- FIX: Use the trade_id from live.py, don't generate a new one ---
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
            "size": trade_data.get("size", "full")
        }
        
        # Filter out any keys that might have a None value
        contract_info = {k: v for k, v in contract_info.items() if v is not None}

        with self._lock:
            if channel_id_str not in self._positions:
                self._positions[channel_id_str] = []
            self._positions[channel_id_str].append(contract_info)
            self._save()
        print(f"✅ PositionManager: Added position for channel {channel_id_str}: {contract_info}")
        return contract_info

    def find_position(self, channel_id: int, trade_data: dict):
        """
        Finds a specific position for a channel.
        - If only a ticker is provided, it finds the most recent position for that ticker.
        - If no details are provided, it returns the most recently added position (LIFO).
        """
        channel_id_str = str(channel_id)
        with self._lock:
            active_trades = self._positions.get(channel_id_str, [])
            if not active_trades:
                return None

            # If a ticker is provided in the current trade data (e.g., for a trim/exit),
            # find the newest active trade that matches that ticker.
            if trade_data.get("ticker"):
                for trade in reversed(active_trades):
                    if trade.get("symbol") == trade_data.get("ticker"):
                        return trade # Return the newest match for the ticker
            
            # If no identifying info is provided, return the absolute last trade added.
            return active_trades[-1]

    def clear_position(self, channel_id: int, trade_id: str):
        """
        Removes a specific position from the list for a channel using its unique trade_id.
        """
        channel_id_str = str(channel_id)
        with self._lock:
            if channel_id_str in self._positions:
                initial_count = len(self._positions[channel_id_str])
                # Filter out the trade with the matching trade_id
                self._positions[channel_id_str] = [
                    trade for trade in self._positions[channel_id_str] if trade.get("trade_id") != trade_id
                ]
                if len(self._positions[channel_id_str]) < initial_count:
                    self._save()
                    print(f"✅ PositionManager: Cleared position {trade_id} for channel {channel_id_str}")
                # If the list is now empty, remove the channel key
                if not self._positions[channel_id_str]:
                    del self._positions[channel_id_str]
                    self._save()