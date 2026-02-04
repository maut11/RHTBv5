# channels/sean.py
from .base_parser import BaseParser
from datetime import datetime, timezone 

class SeanParser(BaseParser):
    def __init__(self, openai_client, channel_id, config, **kwargs):
        super().__init__(openai_client, channel_id, config, **kwargs)

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

--- DATE RULES (CRITICAL - CONVERT ALL DATES TO YYYY-MM-DD) ---
1.  Today's date is {today_str}. The current year is {current_year}.
2.  You MUST convert ALL expiration dates to YYYY-MM-DD format.
3.  For "0dte" or "0DTE" or "today": Return today's date "{today_str}".
4.  For dates without year (e.g., "1/16", "Jan 17", "Sep 19"):
    - If the date has NOT passed yet this year, use {current_year}.
    - If the date has ALREADY passed this year, use {current_year + 1} (assume LEAPS).
5.  For monthly expirations (e.g., "JAN 2026", "January 2026"): Calculate the third Friday of that month.
6.  CONVERSION EXAMPLES (assuming today is {today_str}):
    - "0dte" → "{today_str}"
    - "1/17" (if Jan 17 is future) → "{current_year}-01-17"
    - "1/17" (if Jan 17 has passed) → "{current_year + 1}-01-17"
    - "Sep 19" → "{current_year}-09-19" (or {current_year + 1} if passed)
    - "JAN 2026" → "2026-01-17" (third Friday of January 2026)

--- OUTPUT FORMAT RULES ---
1.  All JSON keys MUST be lowercase and snake_case (e.g., "option_type").
2.  `ticker`: The stock symbol (e.g., "SPX"). Remove any "$" prefix.
3.  `strike`: The strike price (number).
4.  `type`: The option type ("call" or "put"). 'C' is "call", 'P' is "put".
5.  `price`: The execution price (number). If "BE", return the string "BE".
6.  `expiration`: MUST be in YYYY-MM-DD format (e.g., "2026-01-17").
7.  `size`: The position size ("full", "half", or "lotto"). Default to "full" if not mentioned.

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
- **Exit without price**: If the message clearly indicates closing/exiting a position (e.g., "Closing $X", "Out of $X", "Stopped out" including typos like "stoppedo ut") but does NOT mention a specific price, return "market" as the price. This is still an EXIT action.
- COMMENT: Not a trade instruction. Return null.
- **Missing Info**: Avoid inferring trades from general commentary. If critical info for an action is missing, it is better to return a "null" action.
- **Stop Loss** If the message mentions "Stop Loss" or "SL" this is a stop loss indicator and not a Ticker, Do not assume a SL is a ticker, return null for the ticker and the trading boths fallback logic will fill it in  

ACTION VALUES (CRITICAL - USE EXACTLY THESE):
- Use "buy" for any new position entry
- Use "trim" for any partial exit
- Use "exit" for any full position close
- Use "null" for non-actionable messages

NEVER use variations like "entry", "ENTRY", "BTO", etc. - ALWAYS use the exact values above.

--- FEW-SHOT EXAMPLES ---

**BUY Example 1:**
Message: "$SPY 580c 0dte @ 1.50"
Output: {{"action": "buy", "ticker": "SPY", "strike": 580, "type": "call", "expiration": "{today_str}", "price": 1.50, "size": "full"}}

**BUY Example 2:**
Message: "Opening SPX 6050P Jan 31 at 8.20 - half size"
Output: {{"action": "buy", "ticker": "SPX", "strike": 6050, "type": "put", "expiration": "{current_year}-01-31", "price": 8.20, "size": "half"}}

**BUY Example 3 (Lotto):**
Message: "Lotto play: TSLA 260c 1/17 @ 0.85"
Output: {{"action": "buy", "ticker": "TSLA", "strike": 260, "type": "call", "expiration": "{current_year}-01-17", "price": 0.85, "size": "lotto"}}

**TRIM Example 1:**
Message: "Taking some off SPY at 2.30"
Output: {{"action": "trim", "ticker": "SPY", "price": 2.30}}

**TRIM Example 2 (Reply Context):**
PRIMARY: "Trimming half here at 3.50"
ORIGINAL: "$NVDA 140c Jan 24 @ 2.00"
Output: {{"action": "trim", "ticker": "NVDA", "strike": 140, "type": "call", "expiration": "{current_year}-01-24", "price": 3.50}}

**EXIT Example 1:**
Message: "Out of SPX for 12.50"
Output: {{"action": "exit", "ticker": "SPX", "price": 12.50}}

**EXIT Example 2 (Breakeven):**
Message: "Closing AAPL at BE"
Output: {{"action": "exit", "ticker": "AAPL", "price": "BE"}}

**EXIT Example 3 (Reply with Stop):**
PRIMARY: "Stopped out here at 0.40"
ORIGINAL: "$AMD 145p Feb 7 @ 1.20"
Output: {{"action": "exit", "ticker": "AMD", "strike": 145, "type": "put", "expiration": "{current_year}-02-07", "price": 0.40}}

**EXIT Example 4 (Stop without price / typo):**
Message: "Stoppedo ut $CRML @everyone"
Output: {{"action": "exit", "ticker": "CRML", "price": "market"}}

**EXIT Example 5 (Stop without price):**
Message: "Stopped out of TSLA"
Output: {{"action": "exit", "ticker": "TSLA", "price": "market"}}

**EXIT Example 6 (Multiple tickers, no price):**
Message: "Closing $RKLB and $USAR rolls in deep profits"
Output: [{{"action": "exit", "ticker": "RKLB", "price": "market"}}, {{"action": "exit", "ticker": "USAR", "price": "market"}}]

**COMMENTARY Example 1:**
Message: "Watching GOOGL for a potential entry"
Output: {{"action": "null"}}

**COMMENTARY Example 2:**
Message: "Still holding my SPY position, looking good"
Output: {{"action": "null"}}

**COMMENTARY Example 3 (Weekly Plan):**
Message: "Weekly Trade Plan: Looking at MSFT 420c and META 550c for next week"
Output: {{"action": "null"}}

--- MESSAGE TO PARSE ---
PRIMARY MESSAGE: "{primary_message}"
"""
        if context_message:
            prompt += f'\nORIGINAL MESSAGE (for context): "{context_message}"'

        # Add recent conversation history if available
        if self._message_history and len(self._message_history) > 0:
            history_text = "\n".join(self._message_history)
            prompt += f'''

--- RECENT CONVERSATION HISTORY (for additional context) ---
The following are the last {len(self._message_history)} messages in chronological order (oldest first).
Use this context to understand what positions may be active or what the trader has been discussing.

{history_text}

NOTE: The PRIMARY MESSAGE above is the one you need to parse. The history is only for context.
'''

        return prompt
