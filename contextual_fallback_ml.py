"""
Context-Aware Fallback Matching with Machine Learning

Implements trader behavior analysis and contextual matching to improve
fallback accuracy by learning from historical patterns.
"""

import json
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import pickle
import os

@dataclass
class TraderPattern:
    """Represents learned trader behavior patterns"""
    channel: str
    avg_positions_per_day: float
    common_symbols: List[str]
    preferred_expirations: List[str]  # 0dte, weekly, monthly
    typical_strike_ranges: Dict[str, Tuple[float, float]]  # symbol -> (min, max)
    time_patterns: Dict[int, float]  # hour -> activity_level
    action_sequences: List[str]  # common action patterns
    confidence_score: float

class ContextualFallbackML:
    """
    Machine learning-enhanced fallback system that learns trader patterns
    """
    
    def __init__(self, model_path: str = "trader_patterns.pkl"):
        self.model_path = model_path
        self.trader_patterns = {}  # channel -> TraderPattern
        self.pattern_cache = {}
        self._load_patterns()
    
    def analyze_trader_patterns(self, performance_tracker, days_back: int = 30) -> None:
        """Analyze historical trading data to learn patterns"""
        
        print("🧠 Analyzing trader patterns for ML-enhanced fallback...")
        
        # Get historical data for each channel
        channels = ["Ryan", "Eva", "Will", "Fifi", "Sean"]
        
        for channel in channels:
            try:
                pattern = self._analyze_channel_patterns(
                    performance_tracker, channel, days_back
                )
                if pattern:
                    self.trader_patterns[channel] = pattern
                    print(f"   ✅ Learned patterns for {channel}")
            except Exception as e:
                print(f"   ❌ Error analyzing {channel}: {e}")
        
        self._save_patterns()
        print(f"🧠 Pattern analysis complete. Learned {len(self.trader_patterns)} trader profiles.")
    
    def _analyze_channel_patterns(self, tracker, channel: str, days: int) -> Optional[TraderPattern]:
        """Analyze patterns for a specific channel"""
        
        # Get recent trades
        recent_trades = tracker.get_recent_trades(limit=1000, channel=channel)
        
        if len(recent_trades) < 10:  # Need minimum data
            return None
        
        # Calculate patterns
        symbols = [t.get('ticker', '').upper() for t in recent_trades if t.get('ticker')]
        symbol_counts = {}
        for symbol in symbols:
            symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
        
        # Most common symbols (top 10)
        common_symbols = sorted(symbol_counts.keys(), 
                               key=lambda x: symbol_counts[x], 
                               reverse=True)[:10]
        
        # Preferred expirations
        expirations = []
        for trade in recent_trades:
            exp = trade.get('expiration')
            if exp:
                try:
                    exp_date = datetime.strptime(exp, '%Y-%m-%d')
                    entry_date = datetime.fromisoformat(trade.get('entry_time', '').replace('Z', '+00:00'))
                    days_to_exp = (exp_date - entry_date).days
                    
                    if days_to_exp == 0:
                        expirations.append('0dte')
                    elif days_to_exp <= 7:
                        expirations.append('weekly') 
                    else:
                        expirations.append('monthly')
                except:
                    continue
        
        exp_counts = {}
        for exp in expirations:
            exp_counts[exp] = exp_counts.get(exp, 0) + 1
        
        preferred_exps = sorted(exp_counts.keys(), 
                               key=lambda x: exp_counts[x], 
                               reverse=True)[:3]
        
        # Strike ranges by symbol
        strike_ranges = {}
        for symbol in common_symbols:
            symbol_strikes = [
                float(t.get('strike', 0)) 
                for t in recent_trades 
                if (t.get('ticker', '').upper() == symbol and 
                    t.get('strike') and float(t.get('strike', 0)) > 0)
            ]
            if symbol_strikes:
                strike_ranges[symbol] = (min(symbol_strikes), max(symbol_strikes))
        
        # Time patterns (activity by hour)
        time_patterns = {}
        for trade in recent_trades:
            try:
                entry_time = datetime.fromisoformat(trade.get('entry_time', '').replace('Z', '+00:00'))
                hour = entry_time.hour
                time_patterns[hour] = time_patterns.get(hour, 0) + 1
            except:
                continue
        
        # Normalize time patterns
        total_trades = sum(time_patterns.values()) 
        if total_trades > 0:
            time_patterns = {h: count/total_trades for h, count in time_patterns.items()}
        
        # Action sequences (common patterns like buy->trim->exit)
        action_sequences = []
        # This could be enhanced with more sophisticated sequence analysis
        
        # Calculate confidence based on data quality
        confidence = min(1.0, len(recent_trades) / 100.0)  # More data = higher confidence
        
        return TraderPattern(
            channel=channel,
            avg_positions_per_day=len(recent_trades) / max(days, 1),
            common_symbols=common_symbols,
            preferred_expirations=preferred_exps,
            typical_strike_ranges=strike_ranges,
            time_patterns=time_patterns,
            action_sequences=action_sequences,
            confidence_score=confidence
        )
    
    def predict_best_match(self, channel: str, trade_data: dict, 
                          candidate_positions: List[Dict]) -> Optional[Dict]:
        """Use ML patterns to predict best position match"""
        
        if channel not in self.trader_patterns:
            return None  # No pattern data available
            
        pattern = self.trader_patterns[channel]
        
        # Score each candidate based on learned patterns
        scored_candidates = []
        
        for position in candidate_positions:
            if position.get('status') != 'open':
                continue
                
            score = self._score_position_against_pattern(
                trade_data, position, pattern
            )
            
            if score > 0.3:  # Minimum threshold
                scored_candidates.append((score, position))
        
        if not scored_candidates:
            return None
            
        # Return highest scoring position
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_position = scored_candidates[0]
        
        if best_score > 0.7:  # High confidence
            print(f"🤖 ML prediction (confidence: {best_score:.2f}): {best_position.get('trader_symbol')}")
            return best_position
        
        return None
    
    def _score_position_against_pattern(self, trade_data: dict, 
                                       position: dict, pattern: TraderPattern) -> float:
        """Score a position match based on learned trader patterns"""
        
        score = 0.0
        factors = 0
        
        # Symbol frequency in trader's history
        pos_symbol = position.get('trader_symbol', '').upper()
        if pos_symbol in pattern.common_symbols:
            symbol_rank = pattern.common_symbols.index(pos_symbol)
            # Higher score for more common symbols
            symbol_score = 1.0 - (symbol_rank / len(pattern.common_symbols))
            score += symbol_score * 0.3
            factors += 1
        
        # Strike range patterns
        if pos_symbol in pattern.typical_strike_ranges:
            min_strike, max_strike = pattern.typical_strike_ranges[pos_symbol]
            pos_strike = float(position.get('strike', 0))
            
            if min_strike <= pos_strike <= max_strike:
                score += 0.2  # Within typical range
                factors += 1
            else:
                # Partial credit for being close to range
                if pos_strike < min_strike:
                    closeness = max(0, 1 - (min_strike - pos_strike) / min_strike)
                else:
                    closeness = max(0, 1 - (pos_strike - max_strike) / max_strike)
                score += closeness * 0.1
                factors += 1
        
        # Time pattern matching
        current_hour = datetime.now().hour
        if current_hour in pattern.time_patterns:
            activity_level = pattern.time_patterns[current_hour]
            score += activity_level * 0.2  # Higher score during active hours
            factors += 1
        
        # Expiration preference
        pos_exp = position.get('expiration')
        if pos_exp:
            try:
                exp_date = datetime.strptime(pos_exp, '%Y-%m-%d')
                days_to_exp = (exp_date - datetime.now()).days
                
                exp_type = 'monthly'
                if days_to_exp == 0:
                    exp_type = '0dte'
                elif days_to_exp <= 7:
                    exp_type = 'weekly'
                
                if exp_type in pattern.preferred_expirations:
                    exp_rank = pattern.preferred_expirations.index(exp_type)
                    exp_score = 1.0 - (exp_rank / len(pattern.preferred_expirations))
                    score += exp_score * 0.2
                    factors += 1
                    
            except:
                pass
        
        # Action logic
        action = trade_data.get('action')
        if action in ['trim', 'exit'] and position.get('quantity', 0) > 0:
            score += 0.1  # Logical action for open position
            factors += 1
        
        # Normalize by number of factors considered
        return score / max(factors, 1) if factors > 0 else 0.0
    
    def get_contextual_insights(self, channel: str) -> Dict:
        """Get insights about trader patterns for debugging/analysis"""
        
        if channel not in self.trader_patterns:
            return {"error": f"No pattern data for {channel}"}
        
        pattern = self.trader_patterns[channel]
        
        return {
            "channel": channel,
            "confidence": pattern.confidence_score,
            "avg_daily_positions": pattern.avg_positions_per_day,
            "top_symbols": pattern.common_symbols[:5],
            "preferred_expirations": pattern.preferred_expirations,
            "most_active_hours": sorted(pattern.time_patterns.keys(), 
                                      key=lambda x: pattern.time_patterns[x], 
                                      reverse=True)[:3],
            "symbol_count": len(pattern.typical_strike_ranges)
        }
    
    def _save_patterns(self) -> None:
        """Save learned patterns to disk"""
        try:
            with open(self.model_path, 'wb') as f:
                pickle.dump(self.trader_patterns, f)
        except Exception as e:
            print(f"⚠️ Error saving patterns: {e}")
    
    def _load_patterns(self) -> None:
        """Load learned patterns from disk"""
        try:
            if os.path.exists(self.model_path):
                with open(self.model_path, 'rb') as f:
                    self.trader_patterns = pickle.load(f)
                print(f"🧠 Loaded patterns for {len(self.trader_patterns)} traders")
        except Exception as e:
            print(f"⚠️ Error loading patterns: {e}")
            self.trader_patterns = {}

# Global ML instance
contextual_ml = ContextualFallbackML()

def train_fallback_ml(performance_tracker) -> None:
    """Train the ML system on historical data"""
    contextual_ml.analyze_trader_patterns(performance_tracker)

def get_ml_prediction(channel: str, trade_data: dict, candidates: List[Dict]) -> Optional[Dict]:
    """Get ML-based position prediction"""
    return contextual_ml.predict_best_match(channel, trade_data, candidates)

def get_trader_insights(channel: str) -> Dict:
    """Get insights about trader patterns"""
    return contextual_ml.get_contextual_insights(channel)