# channels/ryan.py - Fixed Ryan Parser for Better Trim/Exit Handling
from datetime import datetime, timezone
from .base_parser import BaseParser

class RyanParser(BaseParser):
    def __init__(self, openai_client, channel_id, config):
        super().__init__(openai_client, channel_id, config)

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
6.  `expiration`: The expiration date in YYYY-MM-DD format.
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
1.  The current year is {current_year}.
2.  If an expiration date in the message does not specify a year, you MUST assume the year is {current_year}.
3.  If no expiration is mentioned at all, it is a 0DTE trade. You MUST use today's date: {today_str}.
4.  The final `expiration` field in the JSON output must always be in YYYY-MM-DD format.

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

Now parse the following:

Title: "{title.strip()}"  
Description: "{description.strip()}"
"""

    def _normalize_entry(self, entry: dict) -> dict:
        title, description = self._current_message_meta if isinstance(self._current_message_meta, tuple) else ("UNKNOWN", self._current_message_meta)
        title_upper = title.strip().upper()

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
        if "avg" in description.lower() or "average" in description.lower() or "adding" in description.lower():
            entry["averaging"] = True

        # Enhanced 0DTE logic - only add expiration for BUY actions if missing
        if entry.get("action") == "buy" and not entry.get("expiration"):
            entry["expiration"] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            print(f"[{self.name}] No expiration found for BUY, defaulting to 0DTE: {entry['expiration']}")

        # For TRIM/EXIT, don't add missing fields - let the system fill them in
        return entry