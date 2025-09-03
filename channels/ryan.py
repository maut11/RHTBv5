# channels/ryan.py - OPTIMIZED Ryan Parser with Fast TRIM/EXIT Regex Parsing
import re
from datetime import datetime, timezone
from .base_parser import BaseParser

class RyanParser(BaseParser):
    def __init__(self, openai_client, channel_id, config):
        super().__init__(openai_client, channel_id, config)
        
        # OPTIMIZATION: Pre-compile regex patterns for speed
        self.trim_exit_patterns = {
            'price': re.compile(r'\$?([0-9]+\.?[0-9]*)', re.IGNORECASE),  # Price like $3.3, 3.3
            'percentage': re.compile(r'\+?([0-9]+)%', re.IGNORECASE),      # +18%, 32%
            'explicit_ticker': re.compile(r'\$([A-Z]{1,5})', re.IGNORECASE),  # $SPX only (with $ prefix)
            'be_pattern': re.compile(r'\b(BE|break.?even)\b', re.IGNORECASE)  # BE, breakeven
        }
        
        # Ryan's common tickers for validation
        self.ryan_common_tickers = ['SPX', 'SPXW', 'NQ', 'ES', 'SPY', 'QQQ']
        
        print(f"✅ [{self.name}] Optimized Ryan parser initialized with fast regex patterns")

    def _fast_trim_exit_parse(self, title: str, description: str) -> dict:
        """SPEED OPTIMIZATION: Fast regex-based parsing for TRIM/EXIT (bypasses OpenAI)"""
        title_upper = title.strip().upper()
        
        if title_upper not in ['TRIM', 'EXIT']:
            return None  # Not a trim/exit - fall back to OpenAI
        
        print(f"⚡ [{self.name}] FAST PARSE: {title_upper} - {description[:50]}...")
        
        result = {
            'action': 'trim' if title_upper == 'TRIM' else 'exit'
        }
        
        # Extract ticker using smart logic for sequential trading
        extracted_ticker = None
        
        # 1. Look for explicit ticker with $ prefix (e.g., "$SPX")
        explicit_match = self.trim_exit_patterns['explicit_ticker'].search(description)
        if explicit_match:
            extracted_ticker = explicit_match.group(1).upper()
            print(f"📊 [{self.name}] Found explicit ticker: {extracted_ticker}")
        
        # 2. If no explicit ticker, this is sequential trading - leave ticker None
        # The trading system will fill it from recent positions
        if extracted_ticker:
            result['ticker'] = extracted_ticker
        else:
            print(f"📈 [{self.name}] No explicit ticker found - using sequential trading logic")
        
        # Check for BE (break even)
        if self.trim_exit_patterns['be_pattern'].search(description):
            result['price'] = 'BE'
            print(f"💹 [{self.name}] Detected BE (breakeven) exit")
        else:
            # Extract price
            price_match = self.trim_exit_patterns['price'].search(description)
            if price_match:
                try:
                    result['price'] = float(price_match.group(1))
                    print(f"💰 [{self.name}] Extracted price: ${result['price']}")
                except ValueError:
                    pass
        
        # Extract percentage (for logging/tracking)
        pct_match = self.trim_exit_patterns['percentage'].search(description)
        if pct_match:
            result['gain_percent'] = int(pct_match.group(1))
            print(f"📈 [{self.name}] Gain: +{result['gain_percent']}%")
        
        print(f"⚡ [{self.name}] FAST PARSED: {result}")
        return result
    
    def parse_message(self, message_meta, received_ts, log_func):
        """OPTIMIZED: Use fast regex for TRIM/EXIT, OpenAI only for BUY"""
        try:
            # Store message meta for other methods
            self._current_message_meta = message_meta
            
            title, description = message_meta if isinstance(message_meta, tuple) else ("UNKNOWN", message_meta)
            title_upper = title.strip().upper()
            
            # ========== SPEED OPTIMIZATION ==========
            # For TRIM/EXIT: Use fast regex parsing (skip OpenAI)
            if title_upper in ['TRIM', 'EXIT']:
                start_time = datetime.now(timezone.utc)
                fast_result = self._fast_trim_exit_parse(title, description)
                
                if fast_result:
                    end_time = datetime.now(timezone.utc)
                    latency_ms = (end_time - start_time).total_seconds() * 1000
                    
                    # Tag as fast parsed for normalization
                    self._fast_parsed = True
                    
                    # Apply normalization
                    normalized_result = self._normalize_entry(fast_result)
                    
                    print(f"⚡ [{self.name}] FAST PARSE completed in {latency_ms:.1f}ms (vs ~2000ms OpenAI)")
                    log_func(f"⚡ FAST PARSE: {title_upper} executed in {latency_ms:.1f}ms")
                    
                    return [normalized_result], latency_ms
            
            # ========== FALLBACK TO OPENAI ==========
            # For BUY (ENTRY) and COMMENT: Use OpenAI (accuracy needed)
            print(f"🤖 [{self.name}] Using OpenAI for {title_upper} (accuracy needed)")
            return super().parse_message(message_meta, received_ts, log_func)
            
        except Exception as e:
            print(f"❌ [{self.name}] Parse error: {e}")
            log_func(f"Parse error in {self.name}: {e}")
            # Fallback to OpenAI if regex fails
            return super().parse_message(message_meta, received_ts, log_func)
    
    def build_prompt(self) -> str:
        today = datetime.now(timezone.utc)
        current_year = today.year
        today_str = today.strftime('%Y-%m-%d')

        title, description = self._current_message_meta if isinstance(self._current_message_meta, tuple) else ("UNKNOWN", self._current_message_meta)

        return f"""
You are a highly accurate data extraction assistant for option trading signals from a trader named Ryan.
Your ONLY job is to extract the specified fields and return a single JSON object based on a strict set of rules.

--- OUTPUT FORMAT RULES ---
1.  All JSON keys MUST be lowercase and snake_case (e.g., "option_type").
2.  `ticker`: The stock symbol (e.g., "SPX").
3.  `strike`: The strike price (number).
4.  `type`: The option type ("call" or "put"). 'C' is "call", 'P' is "put".
5.  `price`: The execution price (number). If "BE", return the string "BE".
6.  `expiration`: The raw expiration text as mentioned in the message (e.g., "Sep 19", "1/16", "0dte").
7.  `size`: The position size (e.g., "small", "lotto", "full"). Default to "full" ONLY if no other size is mentioned.

Messages come from a trader named Ryan and are embedded alerts with one of the following titles: ENTRY, TRIM, EXIT, or COMMENT.

You will receive:
- A **title** indicating the type of action
- A **description** containing the trade message

--- ENHANCED ACTION RULES ---
1. **ENTRY**: Represents a new trade. Must include Ticker, Strike, Option Type, and Entry Price.
2. **TRIM**: Represents a partial take-profit. EXTRACT ANY AVAILABLE INFO and let the system fill in missing details.
3. **EXIT**: Represents a full close of the position. EXTRACT ANY AVAILABLE INFO and let the system fill in missing details.
4. **COMMENT**: Not a trade instruction. Return {{"action": "null"}}.

--- CRITICAL ENHANCEMENT FOR TRIM/EXIT ---
For TRIM and EXIT actions, you should EXTRACT WHATEVER INFORMATION IS AVAILABLE, even if incomplete:
- If only a ticker and price are mentioned → extract those
- If only a price is mentioned → extract that
- If percentage gain is mentioned but no price → still return the action

The trading system will automatically fill in missing contract details from recent positions.

--- DATE RULES ---
1.  Today's date is {today_str}.
2.  For expiration dates, extract and return exactly what is mentioned in the message.
3.  If no expiration is mentioned at all, it is a 0DTE trade. Return "0dte" as the expiration value.
4.  Examples: "1/16" → "1/16", "Sep 19" → "Sep 19", "0dte" → "0dte"
5.  Do NOT interpret or convert dates - just extract the raw expiration text from the message.

--- ENHANCED EXAMPLES ---
**ENTRY Example:**
Title: "ENTRY"
Description: "$SPX 6405c @ 2.8 small"
→ {{"action": "buy", "ticker": "SPX", "strike": 6405, "type": "call", "price": 2.8, "size": "small", "expiration": "{today_str}"}}

**TRIM Example (FIXED):**
Title: "TRIM"  
Description: "$SPX 3.3! +18%"
→ {{"action": "trim", "ticker": "SPX", "price": 3.3}}

**EXIT Example (FIXED):**
Title: "EXIT"
Description: "SL BE, nice scalp +32% Done til afternoon"
→ {{"action": "exit", "price": "BE"}}

--- CRITICAL INSTRUCTION ---
DO NOT return {{"action": "null"}} for TRIM or EXIT actions just because some contract details are missing. 
The trading system is designed to handle incomplete information by looking up recent positions.

Return only the valid JSON object. Do not include explanations or markdown formatting.

ACTION VALUES (CRITICAL - USE EXACTLY THESE):
- Use "buy" for any new position entry
- Use "trim" for any partial exit
- Use "exit" for any full position close
- Use "null" for non-actionable messages

NEVER use variations like "entry", "ENTRY", "BTO", etc. - ALWAYS use the exact values above.

Now parse the following:

Title: "{title.strip()}"  
Description: "{description.strip()}"
"""

    def _normalize_entry(self, entry: dict) -> dict:
        # First call BaseParser's normalization for date handling
        entry = super()._normalize_entry(entry)
        
        # Get message metadata safely
        if self._current_message_meta:
            title, description = self._current_message_meta if isinstance(self._current_message_meta, tuple) else ("UNKNOWN", self._current_message_meta)
            title_upper = title.strip().upper() if title else "UNKNOWN"
            description = description or ""
        else:
            title_upper = "UNKNOWN"
            description = ""

        # Map title to action
        if title_upper == "ENTRY":
            entry["action"] = "buy"
        elif title_upper == "TRIM":
            entry["action"] = "trim"
        elif title_upper == "EXIT":
            entry["action"] = "exit"
        elif title_upper == "COMMENT":
            entry["action"] = "null"

        # Check for averaging indicators
        if description and ("avg" in description.lower() or "average" in description.lower() or "adding" in description.lower()):
            entry["averaging"] = True

        # Enhanced 0DTE logic - only add expiration for BUY actions if missing
        if entry.get("action") == "buy" and not entry.get("expiration"):
            entry["expiration"] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            print(f"[{self.name}] No expiration found for BUY, defaulting to 0DTE: {entry['expiration']}")

        # For TRIM/EXIT, don't add missing fields - let the system fill them in
        
        # OPTIMIZATION: Tag fast-parsed entries
        if hasattr(self, '_fast_parsed') and self._fast_parsed:
            entry['parsing_method'] = 'fast_regex'
            delattr(self, '_fast_parsed')
        else:
            entry['parsing_method'] = 'openai'
            
        return entry