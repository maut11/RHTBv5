# channels/fifi.py - FiFi Channel Parser
# Parses FiFi's (sauced2002) plain-English Discord trading alerts
from .base_parser import BaseParser
from datetime import datetime, timezone, timedelta
import re
import json


class FiFiParser(BaseParser):
    FIFI_ALERT_ROLE_ID = "1369304547356311564"

    # Embedded contract notation: e.g. "BMNR50p" -> ticker=BMNR, strike=50, type=put
    EMBEDDED_CONTRACT_RE = re.compile(r'^([A-Z]+)(\d+(?:\.\d+)?)(c|p|call|put)$', re.IGNORECASE)

    # Stop-out phrases that always mean exit
    STOP_PHRASES = ["stopped out", "got stopped", "stop hit", "stopped on", "stops hit"]

    # Size normalization mapping
    SIZE_MAP = {
        "lotto": "lotto", "tiny": "lotto", "1/8": "lotto", "super small": "lotto",
        "half": "half", "some": "half", "small": "half", "starter": "half",
        "1/4": "half", "couple cons": "half", "1/2": "half",
        "full": "full",
    }

    def __init__(self, openai_client, channel_id, config, **kwargs):
        super().__init__(openai_client, channel_id, config, **kwargs)

    def _get_open_positions_json(self) -> str:
        """Query position ledger for open positions, return compact JSON for prompt."""
        if not self.position_ledger:
            return "[]"
        try:
            positions = self.position_ledger.get_open_positions()
            pos_list = []
            for p in positions:
                pos_list.append({
                    "ticker": p.ticker,
                    "strike": p.strike,
                    "type": p.option_type,
                    "exp": p.expiration,
                    "avg_cost": p.avg_cost_basis,
                    "qty": p.total_quantity
                })
            return json.dumps(pos_list)
        except Exception:
            return "[]"

    def _format_history_with_deltas(self) -> str:
        """Reformat message history from [HH:MM:SS] to [Xm ago] time deltas."""
        if not self._message_history:
            return ""
        now = datetime.now(timezone.utc)
        lines = []
        for msg in self._message_history:
            # Parse the [HH:MM:SS] timestamp from the history entry
            ts_match = re.match(r'^\[(\d{2}):(\d{2}):(\d{2})\]\s*(.*)$', msg)
            if ts_match:
                h, m, s = int(ts_match.group(1)), int(ts_match.group(2)), int(ts_match.group(3))
                content = ts_match.group(4)
                # Build a UTC time for today with the extracted HH:MM:SS
                msg_time = now.replace(hour=h, minute=m, second=s, microsecond=0)
                # If the time is in the future (crossed midnight), subtract a day
                if msg_time > now:
                    msg_time -= timedelta(days=1)
                delta = now - msg_time
                total_minutes = int(delta.total_seconds() / 60)
                if total_minutes < 1:
                    tag = "just now"
                elif total_minutes < 60:
                    tag = f"{total_minutes}m ago"
                else:
                    hours = total_minutes // 60
                    mins = total_minutes % 60
                    tag = f"{hours}h{mins}m ago" if mins else f"{hours}h ago"
                lines.append(f"[{tag}] {content}")
            else:
                lines.append(msg)
        return "\n".join(lines)

    def build_prompt(self) -> str:
        today = datetime.now(timezone.utc)
        current_year = today.year
        today_str = today.strftime('%Y-%m-%d')

        # --- Determine message type and extract content ---
        primary_message = ""
        context_message = ""
        if isinstance(self._current_message_meta, tuple):
            primary_message = str(self._current_message_meta[0])
            context_message = str(self._current_message_meta[1])
        else:
            primary_message = str(self._current_message_meta)

        # --- Enhancement 5: Role ping signal ---
        has_alert_ping = f"<@&{self.FIFI_ALERT_ROLE_ID}>" in primary_message

        # --- Enhancement 1: Position ledger injection ---
        open_positions = self._get_open_positions_json()

        # --- Enhancement 3: Message history with time deltas ---
        history_text = self._format_history_with_deltas()

        # --- Build the prompt ---
        prompt = f"""You are a highly accurate data extraction assistant for option trading signals from a trader named FiFi.
Your ONLY job is to extract EXECUTED trade actions and return a JSON array. Each distinct trade = one object.

--- NEGATIVE CONSTRAINTS (HIGHEST PRIORITY — CHECK THESE FIRST) ---
Before classifying ANY message, check if it matches these patterns. If it does → return [{{"action": "null"}}].

1. CONDITIONAL SETUPS / WATCHLISTS:
   Messages containing "Pullback to", "Rejection of", "Break over", "Break under", or "TP:" with price targets are WATCHLIST posts, NOT live trades → "null".
   Pattern: TICKER + condition + expiry + strike + target prices.
   The 🩸 emoji often marks these watchlist/analysis posts.

2. INTENT / PLANS (not yet executed):
   "Plan:", "I want", "Going to open", "will be looking", "might grab", "eyeing", "watching", "looking at" → "null".
   The action must be DONE, not planned.

3. BARE TICKER MENTIONS:
   Messages that are ONLY a ticker symbol ("$FLNC", "$MRK", "XOM") with no strike/price/action → "null".

4. CORRECTION FRAGMENTS:
   Isolated fragments like "82c", "245p", "9c" without a ticker or price → "null".

5. RECAPS & STOP MANAGEMENT:
   Trim summaries (💇 emoji recaps), "SL is HOD", "stops at BE", "move stops to", video recaps, open position lists → "null".

6. TARGET PRICES: "TP 630", "TP: $A, $B, $C" are targets, NOT trims → "null".

--- OPEN POSITIONS ---
{open_positions}

--- CONTEXT ---
ALERT PING: {str(has_alert_ping).lower()} (Pings = higher likelihood of actionable trade)
PRIMARY: The message to parse.
REPLYING TO: Context for missing details (ticker, strike, expiration).

--- ACTION DEFINITIONS ---
- "buy": EXECUTED new entry.
    - Explicit: "in", "bought", "added", "grabbed", "opening", "back in", "scaling into".
    - Implicit: Ticker+strike+type+price WITHOUT any conditional words from Negative Constraints.
    - "sold" / "asold" (typo) with "from $X" context = TRIM, not buy.
- "trim": Partial take-profit. "trim", "trimmed", "sold half", "sold 1/2", "sold some", "asold" (typo for sold), "taking some off", "scaling out".
    NOTE: "sold all" = EXIT, not trim. "sold" without qualifier + full position context = EXIT.
- "exit": Full close. "out", "all out", "sold all", "closed", "done", "stopped out", "got stopped", "exiting", "rest out".
- "null": Everything else. Commentary, watchlists, analysis, stop management, recaps.

--- MULTI-TRADE DETECTION (CRITICAL) ---
A SINGLE message can contain MULTIPLE trades. Count distinct trades BEFORE generating output.
Each distinct price point, expiration, or ticker = SEPARATE trade object in the array.
Trades are separated by newlines, "/", or listed vertically.
EXAMPLES:
- "in MU weekly $250p $2.80 / in next weeks 250p $6" = TWO buys (different expirations)
- "sold 1/4 MRK $2.60 / trim TSLA $3.7" = TWO trims (different tickers)
- "SPY $670 @ $9.50\\nQQQ $600p @ 11.60" = TWO buys (different tickers)

--- DATE RULES ---
Today: {today_str}. Year: {current_year}.
1. All expirations MUST be YYYY-MM-DD.
2. "0dte"/"today"/"weekly" (current week) → "{today_str}".
3. "next week"/"next weeks" → next Friday from today.
4. Dates without year (e.g., "2/6", "Jan 17"): use {current_year} if future, {current_year + 1} if passed.
5. Monthly (e.g., "JAN 2026") → third Friday of that month.
6. Buy with NO expiration → default "{today_str}".

--- OUTPUT FORMAT ---
Return a JSON array. Even single trades: [{{...}}]. Keys: lowercase snake_case.
- `action`: "buy", "trim", "exit", "null"
- `ticker`: Uppercase, no "$"
- `strike`: Number
- `type`: "call" or "put"
- `price`: Number, "BE", or "market"
- `expiration`: YYYY-MM-DD
- `size`: "full" (default), "half" (1/4, small, starter, couple cons), "lotto" (1/8, tiny, super small, lite)

--- PRICE PARSING ---
- "from $X" = entry price context. Extract the CURRENT price, ignore "from".
  "trimmed spy 7.20 from 4.60" → price is 7.20.

--- FEW-SHOT EXAMPLES ---

**BUY (explicit):**
"in PLTR 2/6 $155p $2.70"
→ [{{"action": "buy", "ticker": "PLTR", "strike": 155, "type": "put", "expiration": "{current_year}-02-06", "price": 2.70, "size": "full"}}]

**BUY (implicit):**
"TSLA 480p 0dte 1.40"
→ [{{"action": "buy", "ticker": "TSLA", "strike": 480, "type": "put", "expiration": "{today_str}", "price": 1.40, "size": "full"}}]

**BUY (lotto):**
"in MO 0dte $61c .08 LOTTO SIZE"
→ [{{"action": "buy", "ticker": "MO", "strike": 61, "type": "call", "expiration": "{today_str}", "price": 0.08, "size": "lotto"}}]

**MULTI-BUY (same ticker, different expirations):**
"in MU weekly $250p 1/8 size $2.80\\nin next weeks 250p 1/2 size $6"
→ [{{"action": "buy", "ticker": "MU", "strike": 250, "type": "put", "expiration": "{today_str}", "price": 2.80, "size": "lotto"}}, {{"action": "buy", "ticker": "MU", "strike": 250, "type": "put", "expiration": "{current_year}-02-11", "price": 6.0, "size": "half"}}]

**MULTI-BUY (different tickers):**
"Added to April puts\\nSPY $670 @ $9.50\\nQQQ $600p @ 11.60"
→ [{{"action": "buy", "ticker": "SPY", "strike": 670, "type": "put", "expiration": "{current_year}-04-17", "price": 9.50, "size": "full"}}, {{"action": "buy", "ticker": "QQQ", "strike": 600, "type": "put", "expiration": "{current_year}-04-17", "price": 11.60, "size": "full"}}]

**TRIM (reply-based):**
PRIMARY: "trim .18"
REPLYING TO: "in MO 0dte $61c .08"
→ [{{"action": "trim", "ticker": "MO", "strike": 61, "type": "call", "price": 0.18}}]

**TRIM (typo "asold"):**
"asold another UPS con here $4.50 from $2"
→ [{{"action": "trim", "ticker": "UPS", "price": 4.50}}]

**EXIT:**
"out TSLA 1.4"
→ [{{"action": "exit", "ticker": "TSLA", "price": 1.40}}]

**EXIT (stopped):**
"got stopped on rest of RGTI"
→ [{{"action": "exit", "ticker": "RGTI", "price": "market"}}]

**NULL (conditional setup - CRITICAL):**
"KEYS\\nPullback to $210 or Over $214.50\\n2/20 $230c\\nTP: $220, $230, $240"
→ [{{"action": "null"}}]

**NULL (watchlist with 🩸):**
"$NVDA 🩸\\nRejection of $185 or Below $180\\n2/20 $175p\\nTP: $176, $172, $165"
→ [{{"action": "null"}}]

**NULL (intent):**
"TSLA Plan: a break under 485.33 I'm adding 0DTE $480p"
→ [{{"action": "null"}}]

**NULL (correction fragment):**
"82c"
→ [{{"action": "null"}}]

**NULL (bare ticker):**
"$FLNC"
→ [{{"action": "null"}}]

--- MESSAGE TO PARSE ---
PRIMARY: "{primary_message}"
"""
        # --- Enhancement 2: Reply context ---
        if context_message:
            prompt += f'\nREPLYING TO: "{context_message}"'

        # --- Enhancement 3: Message history with time deltas ---
        if history_text:
            prompt += f'''

--- RECENT HISTORY (last {len(self._message_history)} messages, oldest first) ---
{history_text}

NOTE: Parse ONLY the PRIMARY message. History is context only.
'''

        return prompt

    def _normalize_entry(self, entry: dict) -> dict:
        """FiFi-specific post-processing after base class date normalization."""
        entry = super()._normalize_entry(entry)

        # --- Stop-out phrase detection (force exit) ---
        raw_msg = str(self._current_message_meta).lower() if self._current_message_meta else ""
        if isinstance(self._current_message_meta, tuple):
            raw_msg = str(self._current_message_meta[0]).lower()
        for phrase in self.STOP_PHRASES:
            if phrase in raw_msg and entry.get('action') not in ('exit', 'null'):
                entry['action'] = 'exit'
                if not entry.get('price'):
                    entry['price'] = 'market'
                break

        # --- Embedded contract notation: "BMNR50p" → ticker/strike/type ---
        ticker = entry.get('ticker', '')
        if ticker and not entry.get('strike'):
            m = self.EMBEDDED_CONTRACT_RE.match(ticker)
            if m:
                entry['ticker'] = m.group(1).upper()
                entry['strike'] = float(m.group(2))
                t = m.group(3).lower()
                entry['type'] = 'call' if t in ('c', 'call') else 'put'

        # --- Size normalization ---
        size = str(entry.get('size', '')).lower().strip()
        if size in self.SIZE_MAP:
            entry['size'] = self.SIZE_MAP[size]
        elif size and size not in ('full', 'half', 'lotto'):
            # Check for substring matches
            for key, val in self.SIZE_MAP.items():
                if key in size:
                    entry['size'] = val
                    break

        # --- Default 0DTE for buys without expiration ---
        if entry.get('action') == 'buy' and not entry.get('expiration'):
            today = datetime.now(timezone.utc)
            entry['expiration'] = today.strftime('%Y-%m-%d')

        # --- Ticker cleanup ---
        if entry.get('ticker'):
            entry['ticker'] = entry['ticker'].upper().lstrip('$')

        return entry
