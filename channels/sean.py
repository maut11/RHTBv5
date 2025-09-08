# channels/sean.py
from .base_parser import BaseParser
from datetime import datetime, timezone 

class SeanParser(BaseParser):
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
You are a highly accurate data extraction assistant for option trading signals from a trader named Sean.
Your ONLY job is to extract the specified fields and return a single JSON object based on a strict set of rules.

--- MESSAGE CONTEXT ---
You will be given a PRIMARY message. If it is a reply to another message, you will also receive the ORIGINAL message for context.
- The PRIMARY message contains the main action (e.g., "closing this", "taking some off").
- The ORIGINAL message contains the details of the trade being acted upon (e.g., ticker, strike, expiration).
- Use the ORIGINAL message to fill in any details like ticker, strike, and expiration that are missing from the PRIMARY message.

--- ACTION DEFINITIONS ---
- "buy": Represents a new trade entry.
- "trim": Represents a partial take-profit.
- "exit": Represents a full close of the position.
- "null": A non-actionable message (e.g., commentary, "watching", "still holding").

--- DATE RULES ---
1.  Today's date is {today_str}.
2.  For expiration dates, extract and return exactly what is mentioned in the message.
3.  If the message mentions "0dte", return "0dte" as the expiration value.
4.  Examples: "1/16" → "1/16", "Sep 19" → "Sep 19", "0dte" → "0dte"
5.  Do NOT interpret or convert dates - just extract the raw expiration text from the message.

--- OUTPUT FORMAT RULES ---
1.  All JSON keys MUST be lowercase and snake_case (e.g., "option_type").
2.  `ticker`: The stock symbol (e.g., "SPX").
3.  `strike`: The strike price (number).
4.  `type`: The option type ("call" or "put"). 'C' is "call", 'P' is "put".
5.  `price`: The execution price (number). If "BE", return the string "BE".
6.  `expiration`: The raw expiration text as mentioned in the message (e.g., "Sep 19", "1/16", "0dte").
7.  `size`: The position size (e.g., "small", "lotto", "full"). Default to "full" ONLY if no other size is mentioned.

--- SIZE RULES ---
- If the message contains "half size", or there is sentiment that it is moderately risky -> size = "half"
- If the message contains "lotto", "very small size", or "very risky" -> size = "lotto"
- If size is not mentioned -> size = "full"

Messages without an explicit trade directive (e.g. "all cash", "still holding", "watching", "flow on", "considering") must be labeled as: "action": "null"

--- WEEKLY TRADE PLAN FILTERING ---
**CRITICAL**: If the message contains weekly trade planning content, return {{"action": "null"}}. Detect these patterns:
- "Weekly Trade Plan", "Week Trade Plan", "Trading Plan for", "Weekly Plan", "Trade Plan:"
- Messages discussing future trade setups without immediate execution prices
- Planning messages that list multiple tickers with targets but no entry prices
- Example: "9/8 Weekly Trade Plan: $DOCS - Taking 9/19 70C or 10/17 70C over 69.8 targeting 73.14" → {{"action": "null"}}

--- EXTRACTION LOGIC & RULES ---
- If multiple tickers, return one object per ticker 
- If info is missing, return as much as can be confidently extracted
- Avoid inferring trades from general commentary or opinions
- ENTRY: Represents a new trade. Must include Ticker, Strike, Option Type, and Entry Price.
  - **PORTFOLIO UPDATE FILTER**: If message contains portfolio status, performance updates, or general commentary about positions, return {{"action": "null"}}.
- TRIM: Represents a partial take-profit. Must include a price.
- EXIT: Represents a full close of the position.
- **Breakeven (BE)**: If the message mentions exiting at "BE", return "BE" as the value for the "price" field for immediate exits only.
- COMMENT: Not a trade instruction. Return null.
- **Missing Info**: Avoid inferring trades from general commentary. If critical info for an action is missing, it is better to return a "null" action.
- **Stop Loss** If the message mentions "Stop Loss" or "SL" this is a stop loss indicator and not a Ticker, Do not assume a SL is a ticker, return null for the ticker and the trading boths fallback logic will fill it in  

ACTION VALUES (CRITICAL - USE EXACTLY THESE):
- Use "buy" for any new position entry
- Use "trim" for any partial exit
- Use "exit" for any full position close
- Use "null" for non-actionable messages

NEVER use variations like "entry", "ENTRY", "BTO", etc. - ALWAYS use the exact values above.


--- MESSAGE TO PARSE ---
PRIMARY MESSAGE: "{primary_message}"
"""
        if context_message:
            prompt += f'\nORIGINAL MESSAGE (for context): "{context_message}"'

        return prompt
