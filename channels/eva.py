from datetime import datetime, timezone
from .base_parser import BaseParser

class EvaParser(BaseParser):
    def __init__(self, openai_client, channel_id, config):
        super().__init__(openai_client, channel_id, config)

    def parse_message(self, message_meta, received_ts, log_func):
        """Pre-filter UPDATE alerts, then use OpenAI for OPEN/CLOSE"""
        try:
            # Store message meta for other methods
            self._current_message_meta = message_meta
            
            title, description = message_meta if isinstance(message_meta, tuple) else ("UNKNOWN", message_meta)
            title_upper = title.strip().upper()
            
            # ========== PRE-FILTERING ==========
            # Filter UPDATE alerts - don't process or send to live feed
            if title_upper == 'UPDATE':
                print(f"🚫 [{self.name}] UPDATE alert filtered out: {description[:50]}...")
                log_func(f"UPDATE alert filtered (not processed): {title}")
                return [], 0  # Return empty result, don't process
            
            # Use OpenAI for OPEN/CLOSE processing
            return super().parse_message(message_meta, received_ts, log_func)
            
        except Exception as e:
            print(f"❌ [{self.name}] Parse error: {e}")
            log_func(f"Parse error in {self.name}: {e}")
            return super().parse_message(message_meta, received_ts, log_func)

    def build_prompt(self) -> str:
        today = datetime.now(timezone.utc)
        current_year = today.year
        today_str = today.strftime('%Y-%m-%d')

        title, description = self._current_message_meta
        return f"""

You are a highly accurate data extraction assistant for option trading signals from a trader named Eva.
Your ONLY job is to extract the specified fields and return a single JSON object based on a strict set of rules.

--- OUTPUT FORMAT RULES ---
1.  All JSON keys MUST be lowercase and snake_case (e.g., "option_type").
2.  `ticker`: The stock symbol (e.g., "SPX").
3.  `strike`: The strike price (number).
4.  `type`: The option type ("call" or "put"). 'C' is "call", 'P' is "put".
5.  `price`: The execution price (number). If "BE", return the string "BE".
6.  `expiration`: The raw expiration text as mentioned in the message (e.g., "Sep 19", "1/16", "0dte").
7.  `size`: The position size (e.g., "small", "lotto", "full"). Default to "full" ONLY if no other size is mentioned.

--- DATE RULES ---
1.  Today's date is {today_str}.
2.  For expiration dates, extract and return exactly what is mentioned in the message.
3.  If the message mentions "0dte", return "0dte" as the expiration value.
4.  Examples: "1/16" → "1/16", "Sep 19" → "Sep 19", "0dte" → "0dte"
5.  Do NOT interpret or convert dates - just extract the raw expiration text from the message.

--- ACTION RULES ---
1.  If Title is "OPEN", the action is "buy", return the ticker, strike, price, type, price, expiration, size
    - **PORTFOLIO UPDATE FILTER**: If message contains portfolio status, performance updates, or general commentary about positions, return {{"action": "null"}}.
2.  For a "CLOSE" Title, the action depends on the Description:
    * If it contains "all out", "fully", or "remaining", "exit most here" the action is "exit".
    * If it contains "some", "scale out", or "partial", the action is "trim".
    * If unsure, default to "exit".
3.  If Title is "UPDATE", the action is "null".
4.  For both Exit and Trim actions you MUST return a contract price if it is present
    - **BE (Breakeven) Logic**: Only return "BE" as price for immediate exits at breakeven.

--- CRITICAL LOGIC RULES ---
1.  **DO NOT ASSUME `type`:** "BTO" (Buy to Open) is NOT a valid type. If the message says "BTO" but does not explicitly mention "C", "P", "call", or "put", you MUST omit the `type` key.
2.  **DO NOT GUESS:** If any field (like `strike` or `expiration`) is missing, you MUST omit that key from the final JSON.
3.  **BE THOROUGH:** For CLOSE actions, you MUST extract the `ticker`, `strike`, and `type` if they are mentioned anywhere in the message.

--- EXAMPLES ---
* Message: Title="OPEN", Description="BTO SPX 08/07/2025 6425 @ 0.57" -> Correct JSON: {{"action": "buy", "ticker": "SPX", "strike": 6425, "price": 0.57, "expiration": "2025-08-07"}}
* Message: Title="CLOSE", Description="STC CRCL 08/15/2025 200C @ 1.94 (all out...)" -> Correct JSON: {{"action": "exit", "ticker": "CRCL", "strike": 200, "type": "call", "price": 1.94, "expiration": "2025-08-15"}}
* Message: Title="CLOSE", Description="STC CRWV... (Good spot to scale out half...)" -> Correct JSON: {{"action": "trim", "ticker": "CRWV", ...}}

--- WEEKLY TRADE PLAN FILTERING ---
**CRITICAL**: If the message contains weekly trade planning content, return {{"action": "null"}}. Detect these patterns:
- "Weekly Trade Plan", "Week Trade Plan", "Trading Plan for", "Weekly Plan", "Trade Plan:"
- Messages discussing future trade setups without immediate execution prices
- Planning messages that list multiple tickers with targets but no entry prices
- Example: "Weekly Trade Plan: $DOCS - Taking 9/19 70C over 69.8 targeting 73.14" → {{"action": "null"}}

--- Additional Rules  ---
-  **Stop Loss** If the message mentions "Stop Loss" or "SL" this is a stop loss indicator and not a Ticker, Do not assume a SL is a ticker, return null for the ticker and the trading boths fallback logic will fill it in  
- **Missing Info**: Avoid inferring trades from general commentary. If critical info for an action is missing, it is better to return a "null" action.
Return only the valid JSON object. Do not include explanations.

ACTION VALUES (CRITICAL - USE EXACTLY THESE):
- Use "buy" for any new position entry
- Use "trim" for any partial exit
- Use "exit" for any full position close
- Use "null" for non-actionable messages

NEVER use variations like "entry", "ENTRY", "BTO", etc. - ALWAYS use the exact values above.


--- MESSAGE TO PARSE ---
Title: "{title.strip()}"
Description: "{description.strip()}"
"""

    def _normalize_entry(self, entry: dict) -> dict:
        # First call BaseParser's normalization for date handling
        entry = super()._normalize_entry(entry)
        
        # --- CRITICAL: Stricter Type Handling ---
        entry_type = str(entry.get("type", "")).upper()
        if 'C' in entry_type or 'CALL' in entry_type:
            entry["type"] = "call"
        elif 'P' in entry_type or 'PUT' in entry_type:
            entry["type"] = "put"
        else:
            # If the type is ambiguous or missing, remove the key.
            if 'type' in entry:
                del entry['type']
        # --- END ---

        if entry.get("action") == "buy":
            entry.setdefault("size", "full")
            if not entry.get("expiration"):
                entry["expiration"] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        
        return entry