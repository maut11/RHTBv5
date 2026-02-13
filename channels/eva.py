# channels/eva.py - Eva Channel Parser
# Hybrid parser for Eva's Discord embed alerts
# Open: Regex first, LLM fallback | Close: LLM with position ledger | Update: Check for STC only
from .base_parser import BaseParser, get_parse_cache
from datetime import datetime, timezone
import re
import time
import json


class EvaParser(BaseParser):
    # ─── Embed Colors ───
    COLOR_OPEN = 65280       # green #00ff00
    COLOR_CLOSE = 16711680   # red #ff0000
    COLOR_UPDATE = 3316464   # blue #329af0

    # ─── BTO/STC Regex: "BTO SPY 01/09/26 694c @ 0.53" ───
    # Groups: ticker, date (MM/DD/YY or MM/DD/YYYY), strike, type (c/p), price
    # Optional quantity prefix: "BTO 4 SPY..."
    _TRADE_PATTERN = re.compile(
        r"(?:BTO|STC)\s+(?:\d+\s+)?(\w+)\s+(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d+(?:\.\d+)?)(c|p)\s*@\s*\$?([\d.]+)",
        re.IGNORECASE,
    )

    # ─── Detect STC in Update embeds ───
    _STC_DETECT = re.compile(r"\bSTC\b", re.IGNORECASE)

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

    def build_prompt(self) -> str:
        """Build LLM prompt for Close alerts and Open fallback."""
        today = datetime.now(timezone.utc)
        today_str = today.strftime('%Y-%m-%d')
        current_year = today.year

        # Get message content
        primary_message = ""
        if isinstance(self._current_message_meta, tuple):
            primary_message = str(self._current_message_meta[1])  # description
        else:
            primary_message = str(self._current_message_meta)

        # Get open positions for context
        open_positions = self._get_open_positions_json()

        prompt = f"""You are a trade signal parser for Eva's options alerts.
Extract trade data and return a JSON object.

--- OPEN POSITIONS (for context) ---
{open_positions}

--- DATE RULES ---
Today: {today_str}. Year: {current_year}.
- Convert ALL dates to YYYY-MM-DD format
- "01/09/26" → "2026-01-09"
- "08/26/2026" → "2026-08-26"

--- OUTPUT FORMAT ---
Return a JSON object with these fields:
- "action": "buy" | "trim" | "exit" | "null"
- "ticker": Uppercase stock symbol (e.g., "SPY")
- "strike": Number (e.g., 694)
- "type": "call" or "put"
- "expiration": YYYY-MM-DD format
- "price": Number (e.g., 0.53)
- "size": "full" (default for buys)

--- ACTION CLASSIFICATION (CRITICAL) ---
For CLOSE (STC) alerts, determine TRIM vs EXIT:

**EXIT (full close):**
- "all out" - closing entire position
- "out on remaining" - closing what's left
- "stop loss hit", "running stop loss" - stopped out
- "all out on runner" - closing final runner

**TRIM (partial close):**
- "trim", "Trim half" - explicit trim
- "scale out", "scale some out" - partial exit
- "out some", "out more" - taking some off
- "leaving a runner", "leave runners" - keeping some
- "Profit", "profit taking" - taking profits
- "exit some", "exit most" - partial (NOT full)
- "Holding 1 left" - keeping position

**CRITICAL RULES:**
1. If text says "leave", "leaving", "holding", "runners" → it's TRIM (partial)
2. "Exiting more" or "exit some" → TRIM (not full exit)
3. "all out" anywhere → EXIT (full close)
4. If unsure, default to TRIM (safer)

--- SHARES (not options) ---
If no strike/type (e.g., "BTO NFLX @ 89.71 (adding shares)"):
- Return {{"action": "null"}} - we only trade options

--- FEW-SHOT EXAMPLES ---

**BUY (Open):**
"BTO SPY 01/09/26 694c @ 0.53 (DAY TRADE/Possible Swing)"
→ {{"action": "buy", "ticker": "SPY", "strike": 694, "type": "call", "expiration": "2026-01-09", "price": 0.53, "size": "full"}}

**EXIT (all out):**
"STC SPY 01/12/26 695C @ 0.86 (all out)"
→ {{"action": "exit", "ticker": "SPY", "strike": 695, "type": "call", "expiration": "2026-01-12", "price": 0.86}}

**EXIT (stopped):**
"STC SPY 01/09/26 694c @ 0.63 (running stop loss hit)"
→ {{"action": "exit", "ticker": "SPY", "strike": 694, "type": "call", "expiration": "2026-01-09", "price": 0.63}}

**TRIM (scale out):**
"STC SPY 01/12/26 695C @ 1.01 (scale out some here)"
→ {{"action": "trim", "ticker": "SPY", "strike": 695, "type": "call", "expiration": "2026-01-12", "price": 1.01}}

**TRIM (leaving runner):**
"STC SPY 01/15/26 700C @ 1.10 (leaving a runner if you want)"
→ {{"action": "trim", "ticker": "SPY", "strike": 700, "type": "call", "expiration": "2026-01-15", "price": 1.10}}

**TRIM (exit some - NOT full):**
"STC AMZN 02/06/26 250C @ 1.63 (Exit most here as a day trade)"
→ {{"action": "trim", "ticker": "AMZN", "strike": 250, "type": "call", "expiration": "2026-02-06", "price": 1.63}}

**NULL (shares):**
"BTO NFLX @ 89.71 (adding shares into IRA)"
→ {{"action": "null"}}

--- MESSAGE TO PARSE ---
"{primary_message}"
"""
        return prompt

    def parse_message(self, message_meta, received_ts, logger, message_history=None):
        """
        Hybrid parsing: Regex first for Open, LLM for Close.
        Eva's embeds arrive as message_meta = (embed_title, embed_description).
        """
        start = time.monotonic()

        # Eva's alerts are always embeds — reject plain text messages
        if not isinstance(message_meta, tuple) or len(message_meta) < 2:
            logger(f"ℹ️ [Eva] Non-embed message, skipping")
            return [], 0

        title, description = message_meta[0], message_meta[1]

        # Cache check
        cache = get_parse_cache()
        cached = cache.get(message_meta, message_history)
        if cached is not None:
            stats = cache.get_stats()
            logger(f"⚡ [Eva] CACHE HIT (hit rate: {stats['hit_rate_pct']}%)")
            return cached

        # Store for prompt building
        self._current_message_meta = message_meta

        # Dispatch based on embed title
        title_clean = (title or "").strip().rstrip(":")  # Handle "Update:" colon
        title_upper = title_clean.upper()
        desc = self._clean_description(description or "")

        result = self._dispatch(title_upper, desc, logger)

        latency_ms = (time.monotonic() - start) * 1000

        # Inject metadata into results
        now = datetime.now(timezone.utc).isoformat()
        for entry in result:
            entry["channel_id"] = self.channel_id
            entry["received_ts"] = now

        # Log
        if result:
            actions = [r.get("action") for r in result]
            logger(f"📊 [Eva] Parsed {len(result)} result(s): {actions} ({latency_ms:.1f}ms)")
        else:
            logger(f"ℹ️ [Eva] No actionable result ({latency_ms:.1f}ms)")

        # Cache result
        out = (result, latency_ms)
        cache.set(message_meta, out, message_history)
        return out

    def _dispatch(self, title_upper, desc, logger):
        """Route to the correct parser based on embed title."""
        if title_upper == "OPEN":
            return self._parse_open(desc, logger)
        elif title_upper == "CLOSE":
            return self._parse_close_llm(desc, logger)
        elif title_upper == "UPDATE":
            # Check for hidden STC alerts in Update embeds
            if self._STC_DETECT.search(desc):
                logger(f"🔍 [Eva] Found STC in Update embed, parsing...")
                return self._parse_close_llm(desc, logger)
            return []  # Pure commentary

        logger(f"ℹ️ [Eva] Unrecognized embed title: '{title_upper}'")
        return []

    def _parse_open(self, desc, logger):
        """Parse OPEN embed: Regex first, LLM fallback."""
        # Try regex first
        match = self._TRADE_PATTERN.search(desc)
        if match:
            ticker = match.group(1).upper()
            date_str = match.group(2)
            strike_str = match.group(3)
            opt_type = match.group(4).lower()
            price = float(match.group(5))

            # Handle decimal strikes (e.g., 157.5)
            strike = float(strike_str) if '.' in strike_str else int(strike_str)

            # Convert date from MM/DD/YY to YYYY-MM-DD
            expiration = self._parse_date(date_str)

            logger(f"🟢 [Eva] OPEN (regex): {ticker} {strike}{opt_type} {expiration} @ ${price:.2f}")

            return [{
                "action": "buy",
                "ticker": ticker,
                "strike": strike,
                "type": "call" if opt_type == "c" else "put",
                "expiration": expiration,
                "price": price,
                "size": "full",
            }]

        # Regex failed - use LLM fallback
        logger(f"⚠️ [Eva] OPEN regex failed, using LLM: {desc[:60]}...")
        return self._parse_with_llm(desc, logger, "OPEN")

    def _parse_close_llm(self, desc, logger):
        """Parse CLOSE embed using LLM for trim vs exit determination."""
        logger(f"🔄 [Eva] CLOSE using LLM: {desc[:60]}...")
        return self._parse_with_llm(desc, logger, "CLOSE")

    def _parse_with_llm(self, desc, logger, embed_type):
        """Use LLM to parse message."""
        if not self.client:
            logger(f"⚠️ [Eva] No OpenAI client, falling back to regex")
            if embed_type == "CLOSE":
                return self._parse_close_regex_fallback(desc, logger)
            return []

        try:
            prompt = self.build_prompt()

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
            )

            content = response.choices[0].message.content
            result = json.loads(content)

            # Handle array or single object
            if isinstance(result, list):
                results = result
            else:
                results = [result]

            # Filter null actions and normalize
            normalized = []
            for entry in results:
                if entry.get("action") in ("buy", "trim", "exit"):
                    # Normalize entry
                    entry = self._normalize_llm_entry(entry)
                    normalized.append(entry)

            if normalized:
                action = normalized[0].get("action", "?")
                ticker = normalized[0].get("ticker", "?")
                emoji = "🟢" if action == "buy" else ("🔴" if action == "exit" else "🟡")
                logger(f"{emoji} [Eva] {embed_type} (LLM): {action.upper()} {ticker}")

            return normalized

        except Exception as e:
            logger(f"❌ [Eva] LLM parse error: {e}")
            if embed_type == "CLOSE":
                return self._parse_close_regex_fallback(desc, logger)
            return []

    def _parse_close_regex_fallback(self, desc, logger):
        """Regex fallback for Close when LLM fails."""
        match = self._TRADE_PATTERN.search(desc)
        if not match:
            logger(f"⚠️ [Eva] CLOSE regex fallback failed: {desc[:60]}")
            return []

        ticker = match.group(1).upper()
        date_str = match.group(2)
        strike_str = match.group(3)
        opt_type = match.group(4).lower()
        price = float(match.group(5))

        strike = float(strike_str) if '.' in strike_str else int(strike_str)
        expiration = self._parse_date(date_str)

        # Simple keyword-based action determination
        desc_lower = desc.lower()
        action = self._determine_close_action(desc_lower)

        emoji = "🔴" if action == "exit" else "🟡"
        logger(f"{emoji} [Eva] CLOSE (regex fallback): {action.upper()} {ticker}")

        return [{
            "action": action,
            "ticker": ticker,
            "strike": strike,
            "type": "call" if opt_type == "c" else "put",
            "expiration": expiration,
            "price": price,
        }]

    def _determine_close_action(self, desc_lower: str) -> str:
        """Keyword-based trim vs exit for regex fallback."""
        # TRIM keywords (check first - higher priority)
        trim_keywords = [
            "leaving a runner", "leave runners", "leaving runners",
            "holding", "leave 1", "leave one",
            "exit some", "exit most", "exiting more",
            "out some", "out more",
            "trim", "scale out", "scale some",
            "profit",
        ]
        for keyword in trim_keywords:
            if keyword in desc_lower:
                return "trim"

        # EXIT keywords
        exit_keywords = [
            "all out", "out on remaining",
            "stop loss hit", "running stop loss", "stopped out",
        ]
        for keyword in exit_keywords:
            if keyword in desc_lower:
                return "exit"

        # Default to trim (safer)
        return "trim"

    def _normalize_llm_entry(self, entry: dict) -> dict:
        """Normalize LLM output."""
        # Uppercase ticker
        if entry.get("ticker"):
            entry["ticker"] = entry["ticker"].upper().lstrip("$")

        # Normalize option type
        opt_type = entry.get("type", "").lower()
        if opt_type in ("c", "call"):
            entry["type"] = "call"
        elif opt_type in ("p", "put"):
            entry["type"] = "put"

        # Ensure price is numeric
        price = entry.get("price")
        if isinstance(price, str):
            try:
                entry["price"] = float(price.replace("$", ""))
            except:
                entry["price"] = "market"

        return entry

    def _parse_date(self, date_str: str) -> str:
        """Convert MM/DD/YY or MM/DD/YYYY to YYYY-MM-DD format."""
        parts = date_str.split("/")
        if len(parts) != 3:
            return datetime.now(timezone.utc).strftime("%Y-%m-%d")

        month, day, year = parts
        month = int(month)
        day = int(day)
        year = int(year)

        # Handle 2-digit year
        if year < 100:
            year += 2000

        return f"{year:04d}-{month:02d}-{day:02d}"

    @staticmethod
    def _clean_description(desc: str) -> str:
        """Strip formatting and normalize whitespace."""
        desc = desc.replace("**", "")
        desc = re.sub(r"\s+", " ", desc).strip()
        return desc
