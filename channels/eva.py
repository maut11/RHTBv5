from datetime import datetime, timezone
from .base_parser import BaseParser

class EvaParser(BaseParser):
    def __init__(self, openai_client, channel_id, config):
        super().__init__(openai_client, channel_id, config)

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
6.  `expiration`: The expiration date in YYYY-MM-DD format.
7.  `size`: The position size (e.g., "small", "lotto", "full"). Default to "full" ONLY if no other size is mentioned.

--- DATE RULES ---
1.  Today's date is {today_str}. The current year is {current_year}.
2.  **PRIORITY 1: Explicit Year.** If a full date with a year is provided (e.g., "09/18/2026", "Sep 18, 2026"), you MUST use that exact year. Do NOT change it to the current year unless the provided year is in the past.
3.  **PRIORITY 2: No Year.** If an expiration date does not specify a year (e.g., "Sep 19"), you MUST assume the year is {current_year}.
4.  **Final Format.** The final `expiration` field in the JSON output MUST always be in YYYY-MM-DD format.

--- ACTION RULES ---
1.  If Title is "OPEN", the action is "buy", return the stickern strick pricem type, price expiration, size
2.  For a "CLOSE" Title, the action depends on the Description:
    * If it contains "all out", "fully", or "remaining", "exit most here" the action is "exit".
    * If it contains "some", "scale out", or "partial", the action is "trim".
    * If unsure, default to "exit".
3.  If Title is "UPDATE", the action is "null".
4.  For both Exit and Trim actions you MUST return a contract price if it is present

--- CRITICAL LOGIC RULES ---
1.  **DO NOT ASSUME `type`:** "BTO" (Buy to Open) is NOT a valid type. If the message says "BTO" but does not explicitly mention "C", "P", "call", or "put", you MUST omit the `type` key.
2.  **DO NOT GUESS:** If any field (like `strike` or `expiration`) is missing, you MUST omit that key from the final JSON.
3.  **BE THOROUGH:** For CLOSE actions, you MUST extract the `ticker`, `strike`, and `type` if they are mentioned anywhere in the message.

--- EXAMPLES ---
* Message: Title="OPEN", Description="BTO SPX 08/07/2025 6425 @ 0.57" -> Correct JSON: {{"action": "buy", "ticker": "SPX", "strike": 6425, "price": 0.57, "expiration": "2025-08-07"}}
* Message: Title="CLOSE", Description="STC CRCL 08/15/2025 200C @ 1.94 (all out...)" -> Correct JSON: {{"action": "exit", "ticker": "CRCL", "strike": 200, "type": "call", "price": 1.94, "expiration": "2025-08-15"}}
* Message: Title="CLOSE", Description="STC CRWV... (Good spot to scale out half...)" -> Correct JSON: {{"action": "trim", "ticker": "CRWV", ...}}

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
        # This function is now much simpler as the prompt is more direct.
        
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