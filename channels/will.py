# channels/will.py
from .base_parser import BaseParser
from datetime import datetime, timezone

# --- Channel-specific Parser ---
CHANNEL_ID = 1257442835465244732

class WillParser(BaseParser):
    def __init__(self, openai_client, channel_id, config):
        super().__init__(openai_client, channel_id, config)

    def build_prompt(self) -> str:
        # --- Dynamically get the current date ---
        today = datetime.now(timezone.utc)
        current_year = today.year
        today_str = today.strftime('%Y-%m-%d')

        # --- Handle standard messages and replies ---
        primary_message = ""
        context_message = ""
        if isinstance(self._current_message_meta, tuple):
            # It's a reply: (current_message, original_message)
            primary_message = self._current_message_meta[0]
            context_message = self._current_message_meta[1]
        else:
            # It's a standard message
            primary_message = self._current_message_meta

        # --- Construct the prompt ---
        prompt = f"""
You are a trading assistant extracting structured data from messages by a trader named Will.
Your job is to classify each message and return a **list of JSON objects**, one per action identified.

--- MESSAGE CONTEXT ---
You will be given a PRIMARY message. If it is a reply to another message, you will also receive the ORIGINAL message for context.
- The PRIMARY message contains the main action (e.g., "closing this", "taking some off").
- The ORIGINAL message contains the details of the trade being acted upon (e.g., ticker, strike, expiration).
- Use the ORIGINAL message to fill in any details like ticker, strike, and expiration that are missing from the PRIMARY message.

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


--- ACTION DEFINITIONS ---
- "buy": Represents a new trade entry.
- "trim": Represents a partial take-profit.
- "exit": Represents a full close of the position.
- "null": A non-actionable message (e.g., commentary, "watching", "still holding").

--- DATE RULES ---
1.  The current year is {current_year}. Today's date is {today_str}.
2.  If an expiration date in the message does not specify a year (e.g., "Sep 19"), you MUST assume the year is {current_year}.
3.  If the message mentions "0dte", you MUST return today's date: {today_str}.
4.  The final `expiration` field in the JSON output must always be in YYYY-MM-DD format.

--- OUTPUT FORMAT RULES ---
1.  All JSON keys MUST be lowercase and snake_case (e.g., "option_type").
2.  `ticker`: The stock symbol (e.g., "SPX").
3.  `strike`: The strike price (number).
4.  `type`: The option type ("call" or "put"). 'C' is "call", 'P' is "put".
5.  `price`: The execution price (number). If "BE", return the string "BE".
6.  `expiration`: The expiration date in YYYY-MM-DD format.
7.  `size`: The position size (e.g., "small", "lotto", "full"). Default to "full" ONLY if no other size is mentioned.

--- SIZE RULES ---
- If the message contains "half size", or there is sentiment that it is moderately risky → size = "half"
- If the message contains "lotto", "very small size", or "very risky" → size = "lotto"
- If size is not mentioned → size = "full"

Messages without an explicit trade directive (e.g. “all cash”, “still holding”, “watching”, “flow on”, “considering”) must be labeled as: "action": "null"

--- EXTRACTION LOGIC & RULES ---
- If multiple tickers, return one object per ticker 
- If info is missing, return as much as can be confidently extracted
- Avoid inferring trades from general commentary or opinions
- ENTRY: Represents a new trade. Must include Ticker, Strike, Option Type, and Entry Price.
- TRIM: Represents a partial take-profit. Must include a price.
- EXIT: Represents a full close of the position.
- **Breakeven (BE): If the message indicates an exit at "BE" or "breakeven", you MUST return "BE" as the value for the "price" field. Example: {{"action": "exit", "price": "BE"}}**
- COMMENT: Not a trade instruction. Return null.
- **Missing Info**: Avoid inferring trades from general commentary. If critical info for an action is missing, it is better to return a "null" action.
-  **Stop Loss** If the message mentions "Stop Loss" or "SL" this is a stop loss indicator and not a Ticker, Do not assume a SL is a ticker, return null for the ticker and the trading boths fallback logic will fill it in  



--- MESSAGE TO PARSE ---
PRIMARY MESSAGE: "{primary_message}"
"""
        if context_message:
            prompt += f'\nORIGINAL MESSAGE (for context): "{context_message}"'

        return prompt

    def _normalize_entry(self, entry: dict) -> dict:
        # Normalize ambiguous sizes
        if entry.get("size") in ("some", "small", "starter"):
            entry["size"] = "half"
        # Standardize exit action
        if entry.get("action") == "exit":
            entry["action"] = "stop"
        return entry
