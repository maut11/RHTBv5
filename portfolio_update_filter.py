"""
Portfolio Update Filter - Prevents portfolio status messages from being processed as trades

This module detects when a message is a portfolio update/status report rather than
an active trading instruction, preventing false trade executions.
"""

import re
from typing import List, Dict, Optional
from datetime import datetime

class PortfolioUpdateFilter:
    """
    Detects and filters out portfolio update messages that should not trigger trades
    """
    
    def __init__(self):
        # Past tense indicators (already completed actions)
        self.past_tense_patterns = [
            r'\b(have|has)\s+(already\s+)?(been\s+)?set\b',
            r'\b(TP|take\s*profit)s?\s+(have\s+been\s+|already\s+)?set\b',
            r'\balready\s+(set|placed|done|executed)\b',
            r'\bwon\'t\s+move\s+(tomorrow|today)\b',
            r'\bnot\s+even\s+going\s+to\s+do\s+anything\b',
            r'\bhave\s+been\s+(set|placed|executed)\b',
        ]
        
        # Status/commentary indicators
        self.status_indicators = [
            r'\bunfortunately\s+I\'m\b',
            r'\bgoing\s+to\s+be\s+on\s+a\s+flight\b',
            r'\bwon\'t\s+be\s+(back\s+)?online\s+until\b',
            r'\bprobably\s+won\'t\s+move\b',
            r'\bI\'m\s+not\s+even\s+going\s+to\b',
            r'\blikely\s+going\s+to\s+be\b',
            r'\bmarket\s+open\s+and\s+won\'t\b',
        ]
        
        # Words that suggest completed actions rather than instructions
        self.completion_words = [
            'already', 'have been', 'has been', 'set', 'placed', 
            'executed', 'done', 'completed'
        ]
        
        # Words that suggest future unavailability/status
        self.unavailability_words = [
            'flight', 'unavailable', 'away', 'offline', 'busy', 
            'won\'t be back', 'can\'t trade'
        ]
    
    def is_portfolio_update(self, message: str, channel: str = None) -> Dict:
        """
        Determine if a message is a portfolio update rather than a trade instruction
        
        Returns:
        {
            'is_update': bool,
            'confidence': float,  # 0.0 to 1.0
            'reasons': List[str], # Why it was classified this way
            'filter_applied': bool  # Whether trades should be filtered
        }
        """
        message_lower = message.lower()
        reasons = []
        confidence = 0.0
        
        # Check for past tense patterns
        past_tense_score = 0
        for pattern in self.past_tense_patterns:
            matches = re.findall(pattern, message_lower, re.IGNORECASE)
            if matches:
                past_tense_score += len(matches) * 0.3
                reasons.append(f"Past tense pattern: '{matches[0]}'")
        
        confidence += min(past_tense_score, 0.6)  # Cap at 0.6
        
        # Check for status indicators
        status_score = 0
        for pattern in self.status_indicators:
            matches = re.findall(pattern, message_lower, re.IGNORECASE)
            if matches:
                status_score += len(matches) * 0.4
                reasons.append(f"Status indicator: '{matches[0]}'")
        
        confidence += min(status_score, 0.7)  # Cap at 0.7
        
        # Check for completion words
        completion_count = sum(1 for word in self.completion_words 
                             if word in message_lower)
        if completion_count > 0:
            confidence += min(completion_count * 0.15, 0.4)
            reasons.append(f"Completion words: {completion_count} found")
        
        # Check for unavailability words
        unavail_count = sum(1 for word in self.unavailability_words 
                          if word in message_lower)
        if unavail_count > 0:
            confidence += min(unavail_count * 0.2, 0.3)
            reasons.append(f"Unavailability indicators: {unavail_count} found")
        
        # Special pattern: "set TP for X cons at Y" (already completed)
        tp_set_pattern = r'set\s+TP\s+for\s+\d+\s+cons?\s+at\s+[\d.]+\b'
        if re.search(tp_set_pattern, message_lower, re.IGNORECASE):
            confidence += 0.8
            reasons.append("Past tense TP setting detected")
        
        # Multiple tickers with different statuses (portfolio overview)
        ticker_pattern = r'\$[A-Z]{2,5}\b'
        tickers = re.findall(ticker_pattern, message.upper())
        unique_tickers = set(tickers)
        
        if len(unique_tickers) >= 3:
            confidence += 0.3
            reasons.append(f"Multiple tickers ({len(unique_tickers)}) suggests portfolio overview")
        
        # Time-based context (discussing future unavailability)
        time_patterns = [
            r'\b\d{1,2}\s*AM\s*(EST|ET)\b',
            r'\bmarket\s+open\b',
            r'\btomorrow\b',
            r'\buntil\s+\d{1,2}\s*AM\b'
        ]
        
        time_mentions = 0
        for pattern in time_patterns:
            if re.search(pattern, message, re.IGNORECASE):
                time_mentions += 1
        
        if time_mentions > 0:
            confidence += min(time_mentions * 0.2, 0.4)
            reasons.append(f"Time-based unavailability mentioned")
        
        # Cap confidence at 1.0
        confidence = min(confidence, 1.0)
        
        # Decision thresholds
        is_update = confidence >= 0.7  # High confidence threshold
        filter_applied = confidence >= 0.5  # More conservative filtering
        
        return {
            'is_update': is_update,
            'confidence': confidence,
            'reasons': reasons,
            'filter_applied': filter_applied
        }
    
    def analyze_parsed_results(self, parsed_results: List[Dict], 
                             original_message: str) -> List[Dict]:
        """
        Analyze parsed results and filter out those from portfolio updates
        """
        filter_result = self.is_portfolio_update(original_message)
        
        if not filter_result['filter_applied']:
            return parsed_results  # No filtering needed
        
        # Log the filtering
        print(f"🛡️ Portfolio update filter applied (confidence: {filter_result['confidence']:.2f})")
        for reason in filter_result['reasons']:
            print(f"   • {reason}")
        
        # Convert all actions to null
        filtered_results = []
        for result in parsed_results:
            if isinstance(result, dict) and result.get('action') != 'null':
                filtered_result = result.copy()
                filtered_result['action'] = 'null'
                filtered_result['filter_reason'] = 'Portfolio update detected'
                filtered_results.append(filtered_result)
            else:
                filtered_results.append(result)
        
        return filtered_results

# Global filter instance
portfolio_filter = PortfolioUpdateFilter()

def filter_portfolio_updates(parsed_results: List[Dict], message: str, channel: str = None) -> List[Dict]:
    """
    Convenience function to filter portfolio updates from parsed results
    """
    return portfolio_filter.analyze_parsed_results(parsed_results, message)

def is_message_portfolio_update(message: str, channel: str = None) -> bool:
    """
    Simple check if message is likely a portfolio update
    """
    result = portfolio_filter.is_portfolio_update(message, channel)
    return result['filter_applied']

# Test the filter with the problematic message
if __name__ == "__main__":
    test_message = """Unfortunately I'm likely going to be on a flight at market open and won't be back online until 11 AM EST. 

$JPM & $RBLX TP's have already been set. 

$UNH probably won't move tomorrow so I'm not even going to do anything. 

$DOCS set TP for 6 cons at 2.25"""
    
    result = portfolio_filter.is_portfolio_update(test_message)
    print(f"Portfolio Update Detection Test:")
    print(f"Is Update: {result['is_update']}")
    print(f"Confidence: {result['confidence']:.2f}")
    print(f"Filter Applied: {result['filter_applied']}")
    print(f"Reasons: {result['reasons']}")