"""
Fallback Cache System for Performance Optimization

Implements intelligent caching for position lookups, symbol variants,
and parsing history to reduce database queries and CSV file reads.
"""

import json
import time
from typing import Dict, List, Optional, Any
from threading import Lock
from collections import defaultdict
import sqlite3
from datetime import datetime, timedelta

class FallbackCacheSystem:
    """
    Intelligent caching system for fallback logic components
    """
    
    def __init__(self, cache_ttl: int = 300):  # 5 minutes default TTL
        self.cache_ttl = cache_ttl
        self.lock = Lock()
        
        # Cache storage
        self.position_cache = {}           # channel_id -> positions
        self.symbol_variant_cache = {}     # symbol -> variants list
        self.parsing_history_cache = {}    # channel -> recent parses
        self.trade_lookup_cache = {}       # (ticker, channel) -> trade_id
        
        # Cache metadata
        self.cache_timestamps = {}
        
    def get_cached_positions(self, channel_id: str) -> Optional[List[Dict]]:
        """Get cached positions for a channel"""
        with self.lock:
            cache_key = f"positions_{channel_id}"
            
            if cache_key in self.position_cache:
                timestamp = self.cache_timestamps.get(cache_key, 0)
                if time.time() - timestamp < self.cache_ttl:
                    return self.position_cache[cache_key]
                else:
                    # Clean expired cache
                    del self.position_cache[cache_key]
                    del self.cache_timestamps[cache_key]
            
            return None
    
    def cache_positions(self, channel_id: str, positions: List[Dict]) -> None:
        """Cache positions for a channel"""
        with self.lock:
            cache_key = f"positions_{channel_id}"
            self.position_cache[cache_key] = positions.copy()
            self.cache_timestamps[cache_key] = time.time()
    
    def get_cached_symbol_variants(self, symbol: str) -> Optional[List[str]]:
        """Get cached symbol variants"""
        with self.lock:
            if symbol in self.symbol_variant_cache:
                timestamp = self.cache_timestamps.get(f"symbol_{symbol}", 0)
                if time.time() - timestamp < self.cache_ttl * 4:  # Longer TTL for variants
                    return self.symbol_variant_cache[symbol]
            return None
    
    def cache_symbol_variants(self, symbol: str, variants: List[str]) -> None:
        """Cache symbol variants"""
        with self.lock:
            self.symbol_variant_cache[symbol] = variants.copy()
            self.cache_timestamps[f"symbol_{symbol}"] = time.time()
    
    def get_cached_parsing_history(self, channel: str) -> Optional[List[Dict]]:
        """Get cached parsing history for channel"""
        with self.lock:
            cache_key = f"parsing_{channel}"
            if cache_key in self.parsing_history_cache:
                timestamp = self.cache_timestamps.get(cache_key, 0)
                if time.time() - timestamp < self.cache_ttl // 2:  # Shorter TTL for parsing history
                    return self.parsing_history_cache[cache_key]
            return None
    
    def cache_parsing_history(self, channel: str, history: List[Dict]) -> None:
        """Cache parsing history for channel"""
        with self.lock:
            cache_key = f"parsing_{channel}"
            self.parsing_history_cache[cache_key] = history.copy()
            self.cache_timestamps[cache_key] = time.time()
    
    def get_cached_trade_lookup(self, ticker: str, channel: str) -> Optional[str]:
        """Get cached trade ID lookup"""
        with self.lock:
            cache_key = f"trade_{ticker}_{channel}"
            if cache_key in self.trade_lookup_cache:
                timestamp = self.cache_timestamps.get(cache_key, 0)
                if time.time() - timestamp < self.cache_ttl // 3:  # Even shorter TTL for trade lookups
                    return self.trade_lookup_cache[cache_key]
            return None
    
    def cache_trade_lookup(self, ticker: str, channel: str, trade_id: str) -> None:
        """Cache trade ID lookup"""
        with self.lock:
            cache_key = f"trade_{ticker}_{channel}"
            self.trade_lookup_cache[cache_key] = trade_id
            self.cache_timestamps[cache_key] = time.time()
    
    def clear_expired_cache(self) -> None:
        """Clear all expired cache entries"""
        with self.lock:
            current_time = time.time()
            expired_keys = []
            
            for cache_key, timestamp in self.cache_timestamps.items():
                if current_time - timestamp > self.cache_ttl:
                    expired_keys.append(cache_key)
            
            for cache_key in expired_keys:
                # Remove from appropriate cache
                if cache_key.startswith("positions_"):
                    del self.position_cache[cache_key]
                elif cache_key.startswith("symbol_"):
                    symbol = cache_key.replace("symbol_", "")
                    del self.symbol_variant_cache[symbol]
                elif cache_key.startswith("parsing_"):
                    del self.parsing_history_cache[cache_key]
                elif cache_key.startswith("trade_"):
                    del self.trade_lookup_cache[cache_key]
                
                del self.cache_timestamps[cache_key]
            
            if expired_keys:
                print(f"🧹 Cleared {len(expired_keys)} expired cache entries")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics"""
        with self.lock:
            return {
                "position_cache_size": len(self.position_cache),
                "symbol_variant_cache_size": len(self.symbol_variant_cache),
                "parsing_history_cache_size": len(self.parsing_history_cache),
                "trade_lookup_cache_size": len(self.trade_lookup_cache),
                "total_cached_items": len(self.cache_timestamps),
                "cache_ttl": self.cache_ttl,
                "oldest_cache_age": (time.time() - min(self.cache_timestamps.values())) if self.cache_timestamps else 0
            }

class OptimizedParsingHistoryReader:
    """
    Optimized CSV parsing history reader with indexing and caching
    """
    
    def __init__(self, csv_path: str = "parsing_feedback.csv"):
        self.csv_path = csv_path
        self.cache = FallbackCacheSystem()
        self.channel_index = defaultdict(list)  # channel -> row indices
        self.last_modified = 0
        self.lock = Lock()
    
    def _build_index(self) -> None:
        """Build index of CSV file for fast channel-based lookups"""
        try:
            import os
            import csv
            
            # Check if file was modified
            current_modified = os.path.getmtime(self.csv_path)
            if current_modified <= self.last_modified:
                return  # Index still valid
            
            self.channel_index.clear()
            
            with open(self.csv_path, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)
                
                for row_idx, row in enumerate(reader):
                    if len(row) >= 3:
                        channel = row[0]
                        self.channel_index[channel].append(row_idx)
            
            self.last_modified = current_modified
            print(f"📊 Built parsing history index: {len(self.channel_index)} channels indexed")
            
        except Exception as e:
            print(f"⚠️ Error building parsing history index: {e}")
    
    def get_recent_parses_for_channel(self, channel_name: str, limit: int = 50) -> List[Dict]:
        """Get recent parses for channel with optimized lookup"""
        
        # Check cache first
        cached = self.cache.get_cached_parsing_history(channel_name)
        if cached:
            return cached
        
        with self.lock:
            self._build_index()
            
            if channel_name not in self.channel_index:
                return []
            
            # Get recent row indices for this channel
            channel_rows = self.channel_index[channel_name][-limit:]  # Last N rows
            
            results = []
            
            try:
                import csv
                with open(self.csv_path, 'r', newline='', encoding='utf-8') as csvfile:
                    reader = csv.reader(csvfile)
                    all_rows = list(reader)
                    
                    for row_idx in channel_rows:
                        if row_idx < len(all_rows):
                            row = all_rows[row_idx]
                            if len(row) >= 3:
                                try:
                                    parsed_data = json.loads(row[2])
                                    if parsed_data.get('ticker'):
                                        results.append({
                                            'channel': row[0],
                                            'message': row[1],
                                            'parsed': parsed_data,
                                            'row_idx': row_idx
                                        })
                                except json.JSONDecodeError:
                                    continue
            
            except Exception as e:
                print(f"⚠️ Error reading parsing history: {e}")
                return []
            
            # Cache the results
            self.cache.cache_parsing_history(channel_name, results)
            return results

class OptimizedPerformanceTracker:
    """
    Performance tracker with query optimization and caching
    """
    
    def __init__(self, db_file: str):
        self.db_file = db_file
        self.cache = FallbackCacheSystem()
        
    def find_open_trade_by_ticker_cached(self, ticker: str, channel: str = None) -> Optional[str]:
        """Cached version of trade lookup"""
        
        # Check cache first
        if channel:
            cached_id = self.cache.get_cached_trade_lookup(ticker, channel)
            if cached_id:
                return cached_id
        
        # Query database
        try:
            with sqlite3.connect(self.db_file) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                if channel:
                    # Use index on (ticker, channel, status) for fast lookup
                    cursor.execute("""
                        SELECT trade_id FROM trades 
                        WHERE ticker = ? AND channel = ? AND status = 'open'
                        ORDER BY entry_time DESC 
                        LIMIT 1
                    """, (ticker, channel))
                else:
                    cursor.execute("""
                        SELECT trade_id FROM trades 
                        WHERE ticker = ? AND status = 'open'
                        ORDER BY entry_time DESC 
                        LIMIT 1
                    """, (ticker,))
                
                result = cursor.fetchone()
                trade_id = result['trade_id'] if result else None
                
                # Cache the result
                if trade_id and channel:
                    self.cache.cache_trade_lookup(ticker, channel, trade_id)
                
                return trade_id
                
        except Exception as e:
            print(f"⚠️ Error in cached trade lookup: {e}")
            return None

# Global cache instance
fallback_cache = FallbackCacheSystem()

# Integration functions
def get_optimized_parsing_reader() -> OptimizedParsingHistoryReader:
    """Get optimized parsing history reader"""
    return OptimizedParsingHistoryReader()

def get_cache_stats() -> Dict[str, Any]:
    """Get current cache statistics"""
    return fallback_cache.get_cache_stats()

def clear_fallback_cache() -> None:
    """Clear all fallback cache"""
    fallback_cache.clear_expired_cache()