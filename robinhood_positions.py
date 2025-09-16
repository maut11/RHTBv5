# robinhood_positions.py - Robinhood API Position Fallback Utility
"""
Utility to fetch current open positions from Robinhood API as a fallback
when CSV parsing history is unavailable (e.g., fresh installs).
"""

import logging
from typing import Dict, List, Optional, Tuple
from trader import EnhancedRobinhoodTrader

logger = logging.getLogger(__name__)

class RobinhoodPositionFallback:
    """Provides contract info fallback using live Robinhood positions"""
    
    def __init__(self, trader_instance: EnhancedRobinhoodTrader = None):
        self.trader = trader_instance
        self._position_cache = {}
        self._cache_timestamp = 0
        self._cache_ttl = 60  # Cache positions for 60 seconds
        
    def _get_cached_positions(self) -> Optional[List[Dict]]:
        """Get cached positions if still valid"""
        import time
        current_time = time.time()
        if (current_time - self._cache_timestamp) < self._cache_ttl and self._position_cache:
            return self._position_cache.get('positions')
        return None
    
    def _cache_positions(self, positions: List[Dict]) -> None:
        """Cache positions with timestamp"""
        import time
        self._position_cache = {'positions': positions}
        self._cache_timestamp = time.time()
    
    def get_contract_info_for_ticker(self, ticker: str, channel_name: str = None) -> Optional[Dict]:
        """
        Get contract information for a ticker from open Robinhood positions.
        
        Args:
            ticker: The stock symbol to look up
            channel_name: Channel name for logging context
            
        Returns:
            Dict with strike, expiration, type keys if position found, None otherwise
        """
        try:
            # Try cache first
            positions = self._get_cached_positions()
            
            # If no cache, fetch fresh positions
            if positions is None:
                if not self.trader:
                    logger.warning("No trader instance available for position lookup")
                    return None
                    
                logger.info(f"🔍 Fetching open positions from Robinhood API for {ticker} fallback")
                positions = self.trader.get_open_option_positions()
                
                if not positions:
                    logger.info("No open positions found in Robinhood account")
                    return None
                    
                # Cache the results
                self._cache_positions(positions)
                logger.info(f"📊 Found {len(positions)} open positions in Robinhood account")
            
            # Search for matching ticker using correct field name
            matching_positions = []
            for position in positions:
                pos_ticker = position.get('chain_symbol', '').upper()
                if pos_ticker == ticker.upper():
                    matching_positions.append(position)
            
            if not matching_positions:
                logger.info(f"No open position found for {ticker} in Robinhood account")
                return None
            
            # If multiple positions for same ticker, prefer the one with most recent activity
            # or largest quantity as it's likely the one being referenced
            best_position = matching_positions[0]
            if len(matching_positions) > 1:
                logger.info(f"Found {len(matching_positions)} positions for {ticker}, selecting best match")
                # Sort by quantity (descending) then by recent activity
                matching_positions.sort(key=lambda p: float(p.get('quantity', 0)), reverse=True)
                best_position = matching_positions[0]
            
            # Get contract details using second API call (like !positions command)
            try:
                instrument_data = self.trader.get_option_instrument_data(best_position['option'])
                if not instrument_data:
                    logger.warning(f"Could not get instrument data for {ticker}")
                    return None
                
                # Extract contract information from instrument data
                contract_info = {
                    'strike': float(instrument_data['strike_price']),
                    'expiration': self._format_expiration_date(instrument_data['expiration_date']),
                    'type': self._normalize_option_type(instrument_data['type'])
                }
                
            except Exception as e:
                logger.error(f"Error getting instrument data for {ticker}: {e}")
                return None
            
            logger.info(f"✅ Found position fallback for {ticker}: ${contract_info['strike']}{contract_info['type']} {contract_info['expiration']}")
            return contract_info
            
        except Exception as e:
            logger.error(f"❌ Error fetching position info for {ticker}: {str(e)}")
            return None
    
    def _normalize_option_type(self, option_type: str) -> Optional[str]:
        """Normalize option type to expected format"""
        if not option_type:
            return None
        
        option_type = option_type.lower().strip()
        if option_type in ['call', 'c']:
            return 'C'
        elif option_type in ['put', 'p']:
            return 'P'
        else:
            return option_type.upper()
    
    def _format_expiration_date(self, expiration: str) -> str:
        """Format expiration date to expected format"""
        try:
            # Handle different date formats from Robinhood API
            from datetime import datetime
            
            # If it's already in ISO format (2025-01-16), convert to M/D format
            if '-' in expiration and len(expiration) >= 10:
                dt = datetime.strptime(expiration[:10], '%Y-%m-%d')
                return f"{dt.month}/{dt.day}"
            
            # If it's already in M/D format or other format, return as-is
            return expiration
            
        except Exception:
            logger.warning(f"Could not format expiration date {expiration}")
            return expiration
    
    def get_all_open_positions(self) -> List[Dict]:
        """Get all open positions for debugging/logging purposes"""
        try:
            # Try cache first
            positions = self._get_cached_positions()
            
            if positions is None:
                if not self.trader:
                    return []
                    
                positions = self.trader.get_open_option_positions()
                if positions:
                    self._cache_positions(positions)
            
            return positions or []
            
        except Exception as e:
            logger.error(f"❌ Error fetching all positions: {str(e)}")
            return []


# Global instance - will be initialized by trade_executor when needed
_robinhood_fallback = None

def get_robinhood_fallback(trader_instance: EnhancedRobinhoodTrader = None) -> RobinhoodPositionFallback:
    """Get or create global robinhood fallback instance"""
    global _robinhood_fallback
    if _robinhood_fallback is None:
        _robinhood_fallback = RobinhoodPositionFallback(trader_instance)
    elif trader_instance and not _robinhood_fallback.trader:
        _robinhood_fallback.trader = trader_instance
    return _robinhood_fallback

def get_contract_info_for_ticker(ticker: str, trader_instance: EnhancedRobinhoodTrader = None, channel_name: str = None) -> Optional[Dict]:
    """
    Convenience function to get contract info for a ticker using Robinhood API fallback.
    
    Args:
        ticker: Stock symbol to look up
        trader_instance: Robinhood trader instance (optional, will use global if available)
        channel_name: Channel name for logging context
        
    Returns:
        Dict with contract info or None if not found
    """
    fallback = get_robinhood_fallback(trader_instance)
    return fallback.get_contract_info_for_ticker(ticker, channel_name)