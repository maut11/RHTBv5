# channels/fifi.py - Enhanced with "SOLD TO OPEN" Pattern Recognition and Direct Order Recognition
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

--- ENHANCED "SOLD TO OPEN" RECOGNITION ---
**CRITICAL PATTERN**: FiFi often uses "SOLD TO OPEN" language which indicates a SELL-TO-OPEN options strategy (like selling puts for premium collection).

**"SOLD TO OPEN" Patterns that indicate EXIT actions:**
- "SOLD TO OPEN [TICKER] $[STRIKE][TYPE]" → action = "exit" (selling the position)
- "collect $[AMOUNT] in premium" → indicates a selling action
- "SOLD TO OPEN BMNR $50p" → action = "exit", ticker = "BMNR", strike = 50, type = "put"

**Examples:**
- "SOLD TO OPEN BMNR $50p 10/17 collect $1,030 in premium" → {{"action": "exit", "ticker": "BMNR", "strike": 50, "type": "put", "expiration": "2024-10-17"}}
- "SOLD TO OPEN SPY $500c collect premium" → {{"action": "exit", "ticker": "SPY", "strike": 500, "type": "call"}}

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
1.  Today's date is {today_str}.
2.  For expiration dates, extract and return exactly what is mentioned in the message.
3.  Examples: "1/16" → "1/16", "Sep 19" → "Sep 19", "0dte" → "0dte", "Jan 2026" → "Jan 2026", "10/17" → "10/17"
4.  Do NOT interpret or convert dates - just extract the raw expiration text from the message.

--- OUTPUT FORMAT RULES ---
1.  All JSON keys MUST be lowercase and snake_case (e.g., "option_type").
2.  `ticker`: The stock symbol (e.g., "SPX").
3.  `strike`: The strike price (number).
4.  `type`: The option type ("call" or "put"). 'C' is "call", 'P' is "put".
5.  `price`: The execution price (number). If "BE", return the string "BE".
6.  `expiration`: The raw expiration text as mentioned in the message (e.g., "Jan 2026", "10/17", "0dte").
7.  `size`: The position size (e.g., "small", "lotto", "full"). Default to "full" ONLY if no other size is mentioned.

--- SIZE RULES ---
- If the message contains "half size", or there is sentiment that it is moderately risky → size = "half"
- If the message contains "lotto", "very small size", or "very risky" → size = "lotto"
- If size is not mentioned → size = "full"

Messages without an explicit trade directive (e.g. "all cash", "still holding", "watching", "flow on", "considering") must be labeled as: "action": "null"

--- EXTRACTION RULES ---
1.  **Identify Commands**: A message is ONLY a trading command if it contains a clear action word, "SOLD TO OPEN" pattern, or a direct contract specification. If it's just commentary, you MUST return `{{"action": "null"}}`.
2.  **Extract Details**: If it is an explicit command, extract `ticker`, `strike`, `type`, `price`, `expiration`, and `size`.
3.  **Action Words**:
    * "BTO", "buy", "long", "long swing" → "buy"
    * "Trim", "scale out", "taking some off", "selling half" → "trim"
    * "STC", "sell", "exit", "close", "out", "stopped out", "stop hit" → "exit"
    * **"SOLD TO OPEN"** → "exit" (this is FiFi's selling pattern)
4.  **DIRECT ORDER RECOGNITION**: If a message contains ticker + strike + type + expiration + price but no action words, treat as "buy"
5.  **SOLD TO OPEN RECOGNITION**: If message contains "SOLD TO OPEN" pattern, treat as "exit"
6.  **DO NOT GUESS**: If any field is missing, omit the key from the JSON.
7.  **Breakeven (BE)**: If the message mentions exiting at "BE", return "BE" as the value for the "price" field.
8.  **Stop Loss** If the message mentions "Stop Loss" or "SL" this is a stop loss indicator and not a Ticker, Do not assume a SL is a ticker, return null for the ticker and the trading boths fallback logic will fill it in  

--- PREMIUM COLLECTION DETECTION ---
**CRITICAL**: When FiFi mentions collecting premium (e.g., "collect $1,030 in premium"), this indicates a SELLING action:
- Extract the premium amount if mentioned
- This confirms it's an "exit" action
- The premium amount can be used as context but primary focus is on the contract details

--- REPLY MESSAGE PROCESSING ---
When processing replies:
1. Look for action words in the PRIMARY message first
2. If PRIMARY message contains stop-out language, always treat as "exit"
3. If PRIMARY message contains "SOLD TO OPEN", always treat as "exit"
4. Extract contract details from ORIGINAL message if missing from PRIMARY
5. Combine information logically (action from PRIMARY + details from ORIGINAL)

--- ENHANCED EXAMPLES ---
**SOLD TO OPEN Examples:**
Primary: "SOLD TO OPEN BMNR $50p 10/17 collect $1,030 in premium" → {{"action": "exit", "ticker": "BMNR", "strike": 50, "type": "put", "expiration": "2024-10-17"}}

Primary: "SOLD TO OPEN SPY $500c" + Original: "watching SPY calls" → {{"action": "exit", "ticker": "SPY", "strike": 500, "type": "call"}}

**Stop-out Examples:**
Primary: "got stopped out" + Original: "BTO UNH 305C @ 1.50" → {{"action": "exit", "ticker": "UNH", "strike": 305, "type": "call"}}

**Trim Examples:**
Primary: "trim half here @ 3.20" + Original: "UNH 305C" → {{"action": "trim", "ticker": "UNH", "strike": 305, "type": "call", "price": 3.20}}

**Direct Buy Examples:**
Primary: "PLTR $150 put 8/22 $3.40" → {{"action": "buy", "ticker": "PLTR", "strike": 150, "type": "put", "expiration": "2025-08-22", "price": 3.40}}

**Premium Collection Examples:**
Primary: "collect $500 premium on AAPL puts" + context suggesting selling → {{"action": "exit", "ticker": "AAPL", "type": "put"}}

Return only a single, valid JSON object.

--- MESSAGE TO PARSE ---
PRIMARY MESSAGE: "{primary_message}"
"""
        if context_message:
            prompt += f'\nORIGINAL MESSAGE (for context): "{context_message}"'

        return prompt

    def _normalize_entry(self, entry: dict) -> dict:
        """Enhanced normalization with SOLD TO OPEN detection and better size handling"""
        
        # First call BaseParser's normalization for date handling
        entry = super()._normalize_entry(entry)
        
        # Get the original messages for additional processing (with safe null handling)
        primary_message = ""
        context_message = ""
        if self._current_message_meta:
            if isinstance(self._current_message_meta, tuple):
                primary_message = (self._current_message_meta[0] or "").lower()
                context_message = (self._current_message_meta[1] or "").lower()
            else:
                primary_message = (self._current_message_meta or "").lower()
        else:
            primary_message = ""
            context_message = ""

        # Enhanced SOLD TO OPEN detection as fallback
        sold_to_open_phrases = [
            "sold to open", "sto", "selling to open", "sold-to-open",
            "collect premium", "premium collection", "sell to open"
        ]
        
        combined_message = f"{primary_message} {context_message}".lower()
        
        # Check for SOLD TO OPEN patterns
        if any(phrase in combined_message for phrase in sold_to_open_phrases):
            if entry.get("action") != "exit":
                print(f"[FiFi] SOLD TO OPEN detected, changing action to 'exit': {combined_message[:100]}")
                entry["action"] = "exit"
                
                # Try to extract premium amount for context
                import re
                premium_patterns = [
                    r'collect\s*\$?(\d+(?:,\d+)?(?:\.\d+)?)',
                    r'premium\s*\$?(\d+(?:,\d+)?(?:\.\d+)?)',
                    r'\$(\d+(?:,\d+)?(?:\.\d+)?)\s*(?:in\s*)?premium'
                ]
                
                for pattern in premium_patterns:
                    match = re.search(pattern, combined_message)
                    if match:
                        premium_amount = match.group(1).replace(',', '')
                        try:
                            entry["premium_collected"] = float(premium_amount)
                            print(f"[FiFi] Premium amount detected: ${premium_amount}")
                        except:
                            pass
                        break

        # Enhanced stop-out detection as fallback
        stop_phrases = [
            "stopped out", "got stopped", "stop hit", "stop triggered", 
            "hit my stop", "stop loss triggered", "we got stopped"
        ]
        
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

        # Enhanced contract type parsing for FiFi's notation
        if entry.get("ticker"):
            ticker_raw = entry["ticker"]
            
            # Handle embedded type in ticker (e.g., "BMNR50p" → ticker="BMNR", strike=50, type="put")
            import re
            embedded_pattern = r'^([A-Z]+)(\d+(?:\.\d+)?)(c|p|call|put)$'
            match = re.match(embedded_pattern, ticker_raw.upper())
            
            if match:
                entry["ticker"] = match.group(1)
                if not entry.get("strike"):
                    entry["strike"] = float(match.group(2))
                if not entry.get("type"):
                    type_char = match.group(3).lower()
                    if type_char in ['c', 'call']:
                        entry["type"] = "call"
                    elif type_char in ['p', 'put']:
                        entry["type"] = "put"
                print(f"[FiFi] Parsed embedded contract notation: {ticker_raw} → {entry['ticker']} ${entry['strike']}{entry['type']}")

        return entry