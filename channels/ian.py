# channels/ian.py - Ian Channel Parser
# Parses Ian's (ohiain) structured Discord trading alerts
from .base_parser import BaseParser
from datetime import datetime, timezone, timedelta
import re
import json


class IanParser(BaseParser):
    IAN_ALERT_ROLE_ID = "1457740469353058469"

    # Size normalization mapping - Ian uses "X size" format
    SIZE_MAP = {
        "lotto": "lotto", "1/8": "lotto", "1/8th": "lotto", "tiny": "lotto",
        "1/5": "lotto", "1/5th": "lotto",  # Ian's lotto indicator
        "half": "half", "1/2": "half", "1/4": "half", "1/4th": "half",
        "1/3": "half", "1/3rd": "half", "some": "half", "small": "half",
        "full": "full",
    }

    # Stop-out phrases that always mean exit
    STOP_PHRASES = ["stopped out", "got stopped", "stop hit", "stopped on", "stops hit"]

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
            ts_match = re.match(r'^\[(\d{2}):(\d{2}):(\d{2})\]\s*(.*)$', msg)
            if ts_match:
                h, m, s = int(ts_match.group(1)), int(ts_match.group(2)), int(ts_match.group(3))
                content = ts_match.group(4)
                msg_time = now.replace(hour=h, minute=m, second=s, microsecond=0)
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

        # --- Alert ping signal ---
        has_alert_ping = f"<@&{self.IAN_ALERT_ROLE_ID}>" in primary_message

        # --- Position ledger injection ---
        open_positions = self._get_open_positions_json()

        # --- Message history with time deltas ---
        history_text = self._format_history_with_deltas()

        # --- Build the prompt ---
        prompt = f"""You are a highly accurate data extraction assistant for option trading signals from a trader named Ian (ohiain).
Your ONLY job is to extract EXECUTED trade actions and return a JSON array. Each distinct trade = one object.

--- NEGATIVE CONSTRAINTS (HIGHEST PRIORITY — CHECK THESE FIRST) ---
Before classifying ANY message, check if it matches these patterns. If it does → return [{{"action": "null"}}].

1. WATCHLIST / SETUP POSTS (not executed trades):
   Messages with "watching", "on watch", "top watch", "looking at", "looking for", "would like to see", "stalking" → "null".
   Pattern: Discussing potential setups without entry execution.

2. POSITION UPDATES (informational, not actionable):
   "**Position Update:**" followed by positions with percentages (e.g., "+60% into close") → "null".
   "I'm sitting at", "I'm in profit on", "I'm up X%" → "null".

3. MARKET COMMENTARY:
   "Morning family!", market gap descriptions, sector observations, charts without trades → "null".

4. STOP MANAGEMENT (keep as stop_update if specific):
   Generic stop mentions without specific changes → "null".
   But "Moving stop to b/e", "Setting a hard stop @ X", "Moving stops to b/e on:" WITH ticker → "stop_update".

5. BARE TICKER MENTIONS:
   Just "$ASTS looks great", "$CIFR is cooking" without trade action → "null".

6. CONDITIONAL / FUTURE INTENT:
   "I will trim into", "I will look to", "might add", "plan to" → "null". Action must be DONE.

--- OPEN POSITIONS ---
{open_positions}

Use this to resolve ambiguous trims/exits. If a ticker matches an open position, use those contract details.

--- CONTEXT ---
ALERT PING: {str(has_alert_ping).lower()} (Pings = higher likelihood of actionable trade)
PRIMARY: The message to parse.
REPLYING TO: Context for missing details (ticker, strike, expiration).

--- ACTION DEFINITIONS ---

**"buy"**: EXECUTED new entry.
   - Ian's format: "Adding $TICKER STRIKEc/p EXPIRY @PRICE"
   - Size on separate line: "half size", "1/2 size", "1/5th size (LOTTO TRADE)"
   - Stop on separate line: "Stop: LOD", "Stop: Opening Print"
   - Example: "Adding $ASTS 120c Feb 20 @3.80\\n\\nhalf size (9 day + 90/OP reclaim)\\n\\nStop: LOD"

**"trim"**: Partial take-profit.
   - Ian's format: "Trimming X on TICKER here @PRICE +Y%"
   - Examples: "Trimming 1/4th on weeklies here @1.25 +25%"
   - "TRIMMING $CIFR here @ 1.85 +30%"
   - Price after "@" or "here @" is the execution price.
   - Fraction (1/4th, 1/5th) indicates how much was trimmed, NOT size.

**"exit"**: Full position close.
   - Ian's format: "Flat $TICKER @PRICE at b/e"
   - Also: "out", "all out", "done", "stopped out"
   - "Flat" = closed position at breakeven or specified price.

**"stop_update"**: Stop loss level change (NEW - Ian emphasizes stop management).
   - "Moving stop to b/e" (b/e = breakeven)
   - "Moving stops to b/e on:" + list of positions
   - "Setting a hard stop @ X"
   - "stop remains LOD" (LOD = Low of Day)
   - Extract: ticker (if specified), new_stop (price or "b/e" or "LOD")

**"null"**: Everything else. Commentary, watchlists, analysis, position updates.

--- DATE RULES ---
Today: {today_str}. Year: {current_year}.
1. All expirations MUST be YYYY-MM-DD.
2. "0dte"/"today" → "{today_str}".
3. "weekly"/"weeklies" (current week) → current week Friday.
4. "Feb 20", "Jan 16" format → YYYY-MM-DD using current or next year.
5. Buy with NO expiration → default "{today_str}".

--- OUTPUT FORMAT ---
Return a JSON array. Even single trades: [{{...}}]. Keys: lowercase snake_case.
- `action`: "buy", "trim", "exit", "stop_update", "null"
- `ticker`: Uppercase, no "$"
- `strike`: Number
- `type`: "call" or "put"
- `price`: Number, "b/e", or "market"
- `expiration`: YYYY-MM-DD
- `size`: "full" (default), "half" (1/2, 1/4), "lotto" (1/5th, 1/8th)
- `new_stop`: For stop_update only - price or "b/e" or "LOD"

--- FEW-SHOT EXAMPLES ---

**BUY (structured entry):**
"Adding $ASTS 120c Feb 20 @3.80

half size (9 day + 90/OP reclaim)

Stop: LOD

<@&1457740469353058469>"
→ [{{"action": "buy", "ticker": "ASTS", "strike": 120, "type": "call", "expiration": "{current_year}-02-20", "price": 3.80, "size": "half"}}]

**BUY (lotto):**
"Adding $ASTS 100c 16 Jan @.99

1/5th size (LOTTO TRADE)

Stop: Opening Print.

<@&1457740469353058469>"
→ [{{"action": "buy", "ticker": "ASTS", "strike": 100, "type": "call", "expiration": "{current_year}-01-16", "price": 0.99, "size": "lotto"}}]

**BUY (1/2 size):**
"Adding $CIFR 20c 20 Feb @1.42

1/2 size (VWAP reclaim, DTL retest, 35% LOD, 30 min pivot off 9 day undercut)

Stop: LOD

<@&1457740469353058469>"
→ [{{"action": "buy", "ticker": "CIFR", "strike": 20, "type": "call", "expiration": "{current_year}-02-20", "price": 1.42, "size": "half"}}]

**TRIM (with percentage):**
"Trimming 1/4th on weeklies here @1.25 +25% and moving stop to b/e.
Paying for risk on the whole position."
→ [{{"action": "trim", "ticker": "ASTS", "price": 1.25}}, {{"action": "stop_update", "ticker": "ASTS", "new_stop": "b/e"}}]

**TRIM (simple):**
"TRIMMING $UMAC here @ 2.30 +35%

<@&1457740469353058469>"
→ [{{"action": "trim", "ticker": "UMAC", "price": 2.30}}]

**TRIM (core position reply):**
PRIMARY: "Trimming 1/5th @ 4.65 +23%

I have to trim something into this pop!
Paying for risk here, now I can let it breathe."
REPLYING TO: "Adding $ASTS 120c Feb 20 @3.80"
→ [{{"action": "trim", "ticker": "ASTS", "strike": 120, "type": "call", "expiration": "{current_year}-02-20", "price": 4.65}}]

**TRIM (from entry price context):**
"Trimming my core position 4.80 from 3.80 +26%

Derisking at PHOD!

<@&1457740469353058469>"
→ [{{"action": "trim", "ticker": "ASTS", "price": 4.80}}]

**EXIT (flat at b/e):**
"Flat $JOBY @.93 at b/e

5 min ORB break to downside, not holding that sucker.

<@&1457740469353058469>"
→ [{{"action": "exit", "ticker": "JOBY", "price": 0.93}}]

**STOP_UPDATE (moving to b/e):**
"Moving stop on these to OP, I do not want to see these come back."
→ [{{"action": "stop_update", "ticker": "ASTS", "new_stop": "OP"}}]

**STOP_UPDATE (hard stop):**
"Setting a hard stop on these @ .85 as we can reclaim yesterday's close."
→ [{{"action": "stop_update", "new_stop": 0.85}}]

**STOP_UPDATE (multiple positions):**
"Moving stops to b/e on:

$ASTS 100c 16 Jan (lotto) 2/5th left
$ASTS 120c 20 Feb (core position) 4/5th left

<@&1457740469353058469>"
→ [{{"action": "stop_update", "ticker": "ASTS", "strike": 100, "type": "call", "expiration": "{current_year}-01-16", "new_stop": "b/e"}}, {{"action": "stop_update", "ticker": "ASTS", "strike": 120, "type": "call", "expiration": "{current_year}-02-20", "new_stop": "b/e"}}]

**NULL (watchlist):**
"Watching $LMND for a PB buy entry."
→ [{{"action": "null"}}]

**NULL (intent):**
"I will trim 1/5th $CIFR into NHOD push and pay for my risk, everyone."
→ [{{"action": "null"}}]

**NULL (position update):**
"**Position Update:**

$ASTS 100c 16 Jan (lotto) 2/5th left +60% into close
$ASTS 120c 20 Feb (core position) 4/5th left +30% into close"
→ [{{"action": "null"}}]

**NULL (market commentary):**
"Morning family! Markets are gapping down this morning..."
→ [{{"action": "null"}}]

**NULL (chart observation):**
"$CIFR looks awesome, I love this RDR and DTL retest"
→ [{{"action": "null"}}]

--- MESSAGE TO PARSE ---
PRIMARY: "{primary_message}"
"""
        # --- Reply context ---
        if context_message:
            prompt += f'\nREPLYING TO: "{context_message}"'

        # --- Message history with time deltas ---
        if history_text:
            prompt += f'''

--- RECENT HISTORY (last {len(self._message_history)} messages, oldest first) ---
{history_text}

NOTE: Parse ONLY the PRIMARY message. History is context only.
'''

        return prompt

    def _normalize_entry(self, entry: dict) -> dict:
        """Ian-specific post-processing after base class date normalization."""
        entry = super()._normalize_entry(entry)

        # --- Extract raw message for pattern matching ---
        raw_msg = str(self._current_message_meta).lower() if self._current_message_meta else ""
        if isinstance(self._current_message_meta, tuple):
            raw_msg = str(self._current_message_meta[0]).lower()

        # --- Stop-out phrase detection (force exit) ---
        for phrase in self.STOP_PHRASES:
            if phrase in raw_msg and entry.get('action') not in ('exit', 'null', 'stop_update'):
                entry['action'] = 'exit'
                if not entry.get('price'):
                    entry['price'] = 'market'
                break

        # --- Size normalization from "X size" format ---
        size = str(entry.get('size', '')).lower().strip()
        # Direct lookup
        if size in self.SIZE_MAP:
            entry['size'] = self.SIZE_MAP[size]
        elif size and size not in ('full', 'half', 'lotto'):
            # Substring match for compound formats like "1/5th size"
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

        # --- Normalize b/e price to BE for Pydantic validation ---
        price = entry.get('price', '')
        if isinstance(price, str) and price.lower().strip() in ('b/e', 'be', 'breakeven'):
            entry['price'] = 'BE'

        # --- Normalize stop values ---
        # Ian references STOCK prices for stops (e.g., "38", "LOD", "OP"), not option prices.
        # Since we can only act on option prices, normalize ALL stop_updates to breakeven.
        if entry.get('action') == 'stop_update':
            entry['new_stop'] = 'b/e'

        return entry
