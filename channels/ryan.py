# channels/ryan.py
from datetime import datetime, timezone
from .base_parser import BaseParser

# --- Channel-specific Parser ---
CHANNEL_ID = 1072559822366576780

class RyanParser(BaseParser):
    def __init__(self, openai_client, channel_id, config):
        super().__init__(openai_client, channel_id, config)

    def build_prompt(self) -> str:
        today = datetime.now(timezone.utc)
        current_year = today.year
        today_str = today.strftime('%Y-%m-%d')

        title, description = self._current_message_meta if isinstance(self._current_message_meta, tuple) else ("UNKNOWN", self._current_message_meta)

        # FIX: Changed "Eva" to "Ryan" in the prompt's first line.
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

Return a valid JSON object only if the title is ENTRY, TRIM, or EXIT.
Return `null` if the message is COMMENT or not a trade instruction.
--- RULES ---
1. ENTRY: Represents a new trade. Must include Ticker, Strike, Option Type, and Entry Price.
2. TRIM: Represents a partial take-profit. You MUST include the 'price' if it is mentioned in the alert.
3. EXIT: Represents a full close of the position. You MUST include the 'price' if it is mentioned in the alert.
4. COMMENT: Not a trade instruction. Return null.
5. If the title is TRIM or EXIT you will return a Json, even if there is no additional information that you scrape, this is because the trades can be sequential and our discord bot will automically fill in the information, however if there is additional information include it in the JSON object

--- CRITICAL LOGIC FOR EXPIRATION ---
1.  **If and ONLY IF an explicit expiration date (e.g., "10/17", "Oct 17", "2024-10-17") is present in the message, you MUST extract it.**

--- DATE RULES ---
1.  The current year is {current_year}.
2.  If an expiration date in the message does not specify a year, you MUST assume the year is {current_year}.
3.  If no expiration is mentioned at all, it is a 0DTE trade. You MUST use today's date: {today_str}.
4.  The final `expiration` field in the JSON output must always be in YYYY-MM-DD format.

Each message falls into one of these categories:
1. ENTRY
- Represents a new trade.
- Must include: Ticker, Strike price, Option type, and Entry price.
- Optional: Size, Averaging flag, Expiration (if not present, it's a 0DTE trade for today).

2. TRIM
- Represents a partial take-profit.
- Must include a price if one is specified in the message.
- Often Trim messages do not mention the strike price or the expiration date, they will often the sale price which the option contract is sold at, in this case only return the ticker and price

3. EXIT
- Represents a full close of the position.
- Must include a price if one is specified in the message.
- Often Exit messages do not mention the strike price or the expiration date, they will often the sale price which the option contract is sold at, in this case only return the ticker and price

4. COMMENT
- Commentary, not a trade instruction. Return null.

Return only the valid JSON object. Do not include explanations or markdown formatting.

--- Additional Rules  ---
-  **Stop Loss** If the message mentions "Stop Loss" or "SL" this is a stop loss indicator and not a Ticker, Do not assume a SL is a ticker, return null for the ticker and the trading boths fallback logic will fill it in  
- **Missing Info**: Avoid inferring trades from general commentary. If critical info for an action is missing, it is better to return a "null" action.


Now parse the following:

Title: "{title.strip()}"  
Description: "{description.strip()}"
"""

    def _normalize_entry(self, entry: dict) -> dict:
        title, description = self._current_message_meta if isinstance(self._current_message_meta, tuple) else ("UNKNOWN", self._current_message_meta)
        title_upper = title.strip().upper()

        if title_upper == "ENTRY":
            entry["action"] = "buy"
        elif title_upper == "TRIM":
            entry["action"] = "trim"
        elif title_upper == "EXIT":
            entry["action"] = "exit"

        if "avg" in description.lower() or "average" in description.lower() or "adding" in description.lower():
            entry["averaging"] = True

        # --- CORRECTED 0DTE LOGIC ---
        # This logic now correctly handles the `null` from the AI.
        # If the AI returns `null` for expiration (or omits the key), `entry.get("expiration")` will be falsy.
        if not entry.get("expiration"):
            # The key is missing or null, so we set it to today's date for a 0DTE trade.
            entry["expiration"] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            print(f"[{self.name}] No expiration found, defaulting to 0DTE: {entry['expiration']}")

        return entry