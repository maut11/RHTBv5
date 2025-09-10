"""
Enhanced Position Matching Algorithm for Trading Bot Fallback Logic

This module provides improved position matching with confidence scoring,
time-window constraints, and contextual awareness.
"""

import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import math

@dataclass
class MatchScore:
    """Represents the confidence score for a position match"""
    confidence: float  # 0.0 to 1.0
    reasons: List[str]  # Why this match was scored this way
    match_type: str     # exact|symbol|recent|context
    position: Dict      # The matching position

class EnhancedPositionMatcher:
    """
    Enhanced position matcher with confidence scoring and contextual awareness
    """
    
    def __init__(self):
        self.match_cache = {}  # Cache recent matches for performance
        self.cache_ttl = 300   # 5 minutes
        
    def find_best_position_match(self, channel_id: int, trade_data: dict, 
                                active_positions: List[Dict]) -> Optional[Dict]:
        """
        Find the best matching position using enhanced scoring algorithm
        
        Returns the position with highest confidence score above threshold (0.7)
        """
        if not active_positions:
            return None
            
        # Generate match scores for all positions
        match_scores = []
        for position in active_positions:
            if position.get("status") != "open":
                continue
                
            score = self._calculate_match_score(trade_data, position)
            if score.confidence >= 0.3:  # Only consider reasonable matches
                match_scores.append(score)
        
        if not match_scores:
            return None
            
        # Sort by confidence, return highest if above threshold
        match_scores.sort(key=lambda x: x.confidence, reverse=True)
        best_match = match_scores[0]
        
        if best_match.confidence >= 0.7:  # High confidence threshold
            print(f"✅ High confidence match ({best_match.confidence:.2f}): {best_match.match_type}")
            for reason in best_match.reasons:
                print(f"   • {reason}")
            return best_match.position
        elif best_match.confidence >= 0.5:  # Medium confidence
            print(f"⚠️ Medium confidence match ({best_match.confidence:.2f}): {best_match.match_type}")
            print(f"   Consider using !clear command if this seems incorrect")
            return best_match.position
        else:
            print(f"❌ Low confidence matches only ({best_match.confidence:.2f})")
            return None
    
    def _calculate_match_score(self, trade_data: dict, position: dict) -> MatchScore:
        """Calculate comprehensive match score with multiple factors"""
        
        confidence = 0.0
        reasons = []
        match_type = "none"
        
        # Factor 1: Exact Trade ID match (100% confidence)
        if (trade_data.get("trade_id") and 
            trade_data["trade_id"] == position.get("trade_id")):
            return MatchScore(1.0, ["Exact trade ID match"], "exact", position)
        
        # Factor 2: Symbol matching (up to 40% confidence)
        symbol_score, symbol_reasons = self._score_symbol_match(
            trade_data.get("ticker"), position
        )
        confidence += symbol_score * 0.4
        reasons.extend(symbol_reasons)
        if symbol_score > 0:
            match_type = "symbol"
        
        # Factor 3: Contract details matching (up to 30% confidence)
        contract_score, contract_reasons = self._score_contract_match(trade_data, position)
        confidence += contract_score * 0.3
        reasons.extend(contract_reasons)
        
        # Factor 4: Timing relevance (up to 20% confidence)  
        timing_score, timing_reasons = self._score_timing_match(trade_data, position)
        confidence += timing_score * 0.2
        reasons.extend(timing_reasons)
        if timing_score > 0.7 and match_type == "none":
            match_type = "recent"
            
        # Factor 5: Contextual factors (up to 10% confidence)
        context_score, context_reasons = self._score_context_match(trade_data, position)
        confidence += context_score * 0.1
        reasons.extend(context_reasons)
        if context_score > 0.8:
            match_type = "context"
        
        return MatchScore(
            confidence=min(confidence, 1.0),  # Cap at 1.0
            reasons=reasons,
            match_type=match_type,
            position=position
        )
    
    def _score_symbol_match(self, ticker: Optional[str], position: dict) -> Tuple[float, List[str]]:
        """Score symbol matching with variant support"""
        if not ticker:
            return 0.0, []
            
        reasons = []
        
        # Get all position symbols
        position_symbols = [
            position.get("symbol"),
            position.get("trader_symbol"), 
            position.get("broker_symbol")
        ]
        position_symbols = [s.upper() for s in position_symbols if s]
        
        # Add symbol variants
        if position.get("symbol_variants"):
            position_symbols.extend([v.upper() for v in position["symbol_variants"]])
        
        ticker_upper = ticker.upper()
        
        # Exact match
        if ticker_upper in position_symbols:
            reasons.append(f"Exact symbol match: {ticker}")
            return 1.0, reasons
            
        # Variant match (from config)
        from config import get_all_symbol_variants
        ticker_variants = get_all_symbol_variants(ticker)
        
        for variant in ticker_variants:
            if variant.upper() in position_symbols:
                reasons.append(f"Symbol variant match: {ticker} → {variant}")
                return 0.9, reasons
        
        # Fuzzy match for similar tickers (SPY/SPYG, QQQ/QQQS, etc.)
        fuzzy_score = self._fuzzy_symbol_match(ticker_upper, position_symbols)
        if fuzzy_score > 0.7:
            reasons.append(f"Fuzzy symbol match: {ticker} (score: {fuzzy_score:.2f})")
            return fuzzy_score, reasons
            
        return 0.0, []
    
    def _score_contract_match(self, trade_data: dict, position: dict) -> Tuple[float, List[str]]:
        """Score contract detail matching"""
        reasons = []
        score = 0.0
        total_factors = 0
        
        # Strike price match
        trade_strike = trade_data.get("strike")
        pos_strike = position.get("strike")
        if trade_strike and pos_strike:
            total_factors += 1
            if abs(float(trade_strike) - float(pos_strike)) < 0.01:
                score += 1.0
                reasons.append(f"Exact strike match: ${trade_strike}")
            else:
                # Partial credit for close strikes
                diff_pct = abs(float(trade_strike) - float(pos_strike)) / float(pos_strike)
                if diff_pct < 0.02:  # Within 2%
                    score += 0.8
                    reasons.append(f"Close strike match: ${trade_strike} vs ${pos_strike}")
        
        # Expiration match
        trade_exp = trade_data.get("expiration")  
        pos_exp = position.get("expiration")
        if trade_exp and pos_exp:
            total_factors += 1
            if str(trade_exp) == str(pos_exp):
                score += 1.0
                reasons.append(f"Exact expiration match: {trade_exp}")
        
        # Option type match
        trade_type = trade_data.get("type")
        pos_type = position.get("type")
        if trade_type and pos_type:
            total_factors += 1
            if str(trade_type).lower() == str(pos_type).lower():
                score += 1.0
                reasons.append(f"Option type match: {trade_type}")
                
        return (score / max(total_factors, 1)), reasons
    
    def _score_timing_match(self, trade_data: dict, position: dict) -> Tuple[float, List[str]]:
        """Score based on timing relevance"""
        reasons = []
        
        try:
            # Get position creation time
            created_at = position.get("created_at")
            if not created_at:
                return 0.5, ["No timestamp available"]
                
            # Parse timestamp
            if isinstance(created_at, str):
                pos_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            else:
                pos_time = created_at
                
            now = datetime.utcnow()
            time_diff = now - pos_time
            
            # Score based on recency (exponential decay)
            hours_old = time_diff.total_seconds() / 3600
            
            if hours_old < 1:  # Less than 1 hour
                score = 1.0
                reasons.append("Very recent position (< 1 hour)")
            elif hours_old < 6:  # Less than 6 hours  
                score = 0.8
                reasons.append(f"Recent position ({hours_old:.1f} hours old)")
            elif hours_old < 24:  # Less than 1 day
                score = 0.6
                reasons.append(f"Same-day position ({hours_old:.1f} hours old)")
            else:  # Older than 1 day
                score = max(0.2, 1.0 - (hours_old / 168))  # Decay over week
                reasons.append(f"Older position ({hours_old:.1f} hours old)")
                
            return score, reasons
            
        except Exception as e:
            return 0.5, [f"Error parsing timestamp: {e}"]
    
    def _score_context_match(self, trade_data: dict, position: dict) -> Tuple[float, List[str]]:
        """Score based on contextual factors"""
        reasons = []
        score = 0.0
        
        # Market hours context
        now = datetime.now()
        if 9 <= now.hour <= 16:  # Market hours
            score += 0.3
            reasons.append("During market hours")
        
        # Position size context  
        action = trade_data.get("action")
        pos_quantity = position.get("quantity", 0)
        
        if action in ["trim", "exit"] and pos_quantity > 0:
            score += 0.4
            reasons.append(f"Logical action for open position ({action})")
        elif action == "buy":
            # Buying when position exists might be adding to position
            score += 0.2
            reasons.append("Buy action (possibly adding to position)")
            
        # Channel activity pattern (could be enhanced with ML)
        score += 0.3  # Base context score
        reasons.append("Standard trading context")
        
        return score, reasons
    
    def _fuzzy_symbol_match(self, ticker: str, position_symbols: List[str]) -> float:
        """Calculate fuzzy string match for similar tickers"""
        best_score = 0.0
        
        for pos_symbol in position_symbols:
            # Simple similarity based on common prefixes/suffixes
            if len(ticker) >= 3 and len(pos_symbol) >= 3:
                # Check for common patterns like SPY/SPYG, QQQ/QQQS
                if (ticker[:3] == pos_symbol[:3] or  # Common prefix
                    ticker[-3:] == pos_symbol[-3:]):  # Common suffix
                    score = len(set(ticker) & set(pos_symbol)) / max(len(ticker), len(pos_symbol))
                    best_score = max(best_score, score)
                    
        return best_score

# Usage integration point
def integrate_enhanced_matching():
    """Integration point for enhanced matching in position_manager.py"""
    
    # This would replace the existing find_position method
    matcher = EnhancedPositionMatcher()
    
    def enhanced_find_position(self, channel_id: int, trade_data: dict) -> Optional[dict]:
        """Enhanced version of find_position with scoring"""
        channel_id_str = str(channel_id)
        
        with self._lock:
            active_trades = self._positions.get(channel_id_str, [])
            return matcher.find_best_position_match(channel_id, trade_data, active_trades)
    
    return enhanced_find_position