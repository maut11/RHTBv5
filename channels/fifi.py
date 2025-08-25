# channels/fifi.py - Enhanced with direct order recognition
from .base_parser import BaseParser
from datetime import datetime, timezone

class FiFiParser(BaseParser):
    def __init__(self, openai_client, channel_id, config):
        super().__init__(openai_client, channel_id, config)

    def build_prompt(self) -> str:
        # --- Dynamically get the current date ---
        today = datetime.now(timezone.utc)
        current_year = today.year
        today_str = today.strftime('%Y-%m-%d')

        # --- Enhanced reply handling ---
        primary_message = ""
        context_message = ""
        if isinstance(self._current_message_meta, tuple):
            # It's a reply: (current_message, original_message)
            primary_message = self._current_message_meta[0]
            context_message = self._current_message_meta[1]
        else:
            # It's a standard message
            primary_message = self._current_message_meta

        # --- Construct the enhanced prompt ---
        prompt = f"""
You are a highly strict data extraction assistant for a trader named FiFi. Your job is to find explicit trading commands and convert them to a single JSON object. You must ignore all other commentary.

--- MESSAGE CONTEXT ---
You will be given a PRIMARY message. If it is a reply to another message (e.g., "Exiting out of all these positions"), you will also receive the ORIGINAL message for context.
- The PRIMARY message contains the action (e.g., "exit", "trim", "stopped out").
- The ORIGINAL message contains the trade details (e.g., ticker, strike).
- Use the ORIGINAL message to fill in any details missing from the PRIMARY message.

--- ACTION DEFINITIONS ---
- "buy": Represents a new trade entry.
- "trim": Represents a partial take-profit. You MUST extract the 'price' if mentioned.
- "exit": Represents a full close of the position. You MUST extract the 'price' if mentioned.
- "null": A non-actionable message (e.g., commentary, "watching", "still holding").

--- ENHANCED BUY ORDER RECOGNITION ---
**CRITICAL**: If a message contains a ticker, strike, option type, expiration, and price but NO explicit action words, this is a BUY order.

**Pattern Recognition for Direct Buy Orders:**
- "TICKER $STRIKE call/put EXPIRATION $PRICE" → action = "buy"
- "TICKER STRIKE c/p DATE PRICE" → action = "buy"
- "$TICKER $STRIKE call EXPIRATION at $PRICE" → action = "buy"

**Examples of Direct Buy Orders:**
- "PLTR $150 put 8/22 $3.40" → {{"action": "buy", "ticker": "PLTR", "strike": 150, "type": "put", "expiration": "2025-08-22", "price": 3.40}}
- "SPY 500c 8/25 @ 2.50" → {{"action": "buy", "ticker": "SPY", "strike": 500, "type": "call", "expiration": "2025-08-25", "price": 2.50}}
- "AAPL $180 call 9/15 $5.20" → {{"action": "buy", "ticker": "AAPL", "strike": 180, "type": "call", "expiration": "2025-09-15", "price": 5.20}}

--- ENHANCED STOP-OUT DETECTION ---
**CRITICAL**: The following phrases ALWAYS indicate a full exit action:
- "stopped out" (in any form: "stopped out", "got stopped out", "we got stopped", etc.)
- "stop hit" 
- "stop triggered"
- "hit my stop"
- "stop loss triggered"
- When these phrases are detected, set action to "exit" regardless of other context.

--- DATE RULES ---
1.  The current year is {current_year}. Today's date is {today_str}.
2.  If an expiration date in the message does not specify a year (e.g., "Sep 19"), you MUST assume the year is {current_year}.
3.  If the message mentions "0dte", you MUST return today's date: {today_str}.
4.  The final `expiration` field in the JSON output must always be in YYYY-MM-DD format.
5.  **Monthly Expiration Rule**: If an expiration only gives a month and year (e.g., "Jan 2026"), you MUST interpret this as the monthly expiration, which is the third Friday of that month. For example, "Jan 2026" should be parsed as "2026-01-16".

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

Messages without an explicit trade directive (e.g. "all cash", "still holding", "watching", "flow on", "considering") must be labeled as: "action": "null"

--- EXTRACTION RULES ---
1.  **Identify Commands**: A message is ONLY a trading command if it contains a clear action word and a specific contract. If it's just commentary, you MUST return `{{"action": "null"}}`.
2.  **Extract Details**: If it is an explicit command, extract `ticker`, `strike`, `type`, `price`, `expiration`, and `size`.
3.  **Action Words**:
    * "BTO", "buy", "long", "long swing" → "buy"
    * "Trim", "scale out", "taking some off", "selling half" → "trim"
    * "STC", "sell", "exit", "close", "out", "stopped out", "stop hit" → "exit"
4.  **DIRECT ORDER RECOGNITION**: If a message contains ticker + strike + type + expiration + price but no action words, treat as "buy"
5.  **DO NOT GUESS**: If any field is missing, omit the key from the JSON.
6.  **Breakeven (BE)**: If the message mentions exiting at "BE", return "BE" as the value for the "price" field.
7.  **Stop Loss** If the message mentions "Stop Loss" or "SL" this is a stop loss indicator and not a Ticker, Do not assume a SL is a ticker, return null for the ticker and the trading boths fallback logic will fill it in  

--- REPLY MESSAGE PROCESSING ---
When processing replies:
1. Look for action words in the PRIMARY message first
2. If PRIMARY message contains stop-out language, always treat as "exit"
3. Extract contract details from ORIGINAL message if missing from PRIMARY
4. Combine information logically (action from PRIMARY + details from ORIGINAL)

--- EXAMPLES ---
Primary: "got stopped out" + Original: "BTO UNH 305C @ 1.50" → {{"action": "exit", "ticker": "UNH", "strike": 305, "type": "call"}}
Primary: "trim half here @ 3.20" + Original: "UNH 305C" → {{"action": "trim", "ticker": "UNH", "strike": 305, "type": "call", "price": 3.20}}
Primary: "PLTR $150 put 8/22 $3.40" → {{"action": "buy", "ticker": "PLTR", "strike": 150, "type": "put", "expiration": "2025-08-22", "price": 3.40}}

ACTION VALUES (CRITICAL - USE EXACTLY THESE):
- Use "buy" for any new position entry
- Use "trim" for any partial exit
- Use "exit" for any full position close
- Use "null" for non-actionable messages

NEVER use variations like "entry", "ENTRY", "BTO", etc. - ALWAYS use the exact values above.

Return only a single, valid JSON object.

--- MESSAGE TO PARSE ---
PRIMARY MESSAGE: "{primary_message}"
"""
        if context_message:
            prompt += f'\nORIGINAL MESSAGE (for context): "{context_message}"'

        return prompt

    def _normalize_entry(self, entry: dict) -> dict:
        """Enhanced normalization with stop-out detection and better size handling"""
        
        # Get the original messages for additional processing
        primary_message = ""
        context_message = ""
        if isinstance(self._current_message_meta, tuple):
            primary_message = self._current_message_meta[0].lower()
            context_message = self._current_message_meta[1].lower()
        else:
            primary_message = self._current_message_meta.lower()

        # Enhanced stop-out detection as fallback
        stop_phrases = [
            "stopped out", "got stopped", "stop hit", "stop triggered", 
            "hit my stop", "stop loss triggered", "we got stopped"
        ]
        
        combined_message = f"{primary_message} {context_message}".lower()
        if any(phrase in combined_message for phrase in stop_phrases):
            if entry.get("action") != "exit":
                print(f"[FiFi] Stop-out detected, changing action to 'exit': {combined_message[:100]}")
                entry["action"] = "exit"

        # Size normalization
        if entry.get("size") in ("some", "small", "starter"):
            entry["size"] = "half"
        elif entry.get("size") in ("tiny", "lotto"):
            entry["size"] = "lotto"
        elif not entry.get("size"):
            entry["size"] = "full"

        # Enhanced 0DTE handling
        if not entry.get("expiration") and entry.get("action") == "buy":
            entry["expiration"] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            print(f"[FiFi] No expiration found, defaulting to 0DTE: {entry['expiration']}")

        return entry