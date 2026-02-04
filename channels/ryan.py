# channels/ryan.py - Ryan Channel Parser
# Regex-based parser for Ryan's 0DTE SPX Discord embed alerts
# Embeds from "Sir Goldman Alert Bot": title=ENTRY/TRIM/EXIT/COMMENT, description=message text
from .base_parser import BaseParser, get_parse_cache
from datetime import datetime, timezone
import re
import time


class RyanParser(BaseParser):
    # ─── Embed Colors (for fallback dispatch when title is unrecognized) ───
    COLOR_ENTRY = 3066993      # green
    COLOR_TRIM = 16705372      # yellow
    COLOR_EXIT = 15158332      # red
    COLOR_COMMENT = 3447003    # blue

    # ─── ENTRY Regex: "$SPX 6050p @ 2.80" → strike=6050, type=p, price=2.80 ───
    _ENTRY_SPX = re.compile(
        r"\$SPX\s+(\d+)(p|c)\s*@\s*\$?([\d.]+)",
        re.IGNORECASE,
    )

    # ─── Futures filter: ignore non-SPX entries (NQ, GC, ES, CL, YM) ───
    _FUTURES_ENTRY = re.compile(
        r"(?:Long|Short)\s+\$?(?:NQ|GC|ES|CL|YM)",
        re.IGNORECASE,
    )

    # ─── Emoji unicode ranges for cleaning ───
    _EMOJI_RE = re.compile(
        r"[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0000FE00-\U0000FE0F]"
    )

    def __init__(self, openai_client, channel_id, config, **kwargs):
        super().__init__(openai_client, channel_id, config, **kwargs)

    def build_prompt(self) -> str:
        """Not used — RyanParser bypasses LLM. Required by ABC."""
        return ""

    def parse_message(self, message_meta, received_ts, logger, message_history=None):
        """
        Override base parse_message to use regex dispatch instead of LLM.
        Ryan's embeds arrive as message_meta = (embed_title, embed_description).
        Returns (List[Dict], float) matching the base class contract.
        """
        start = time.monotonic()

        # Ryan's alerts are always embeds — reject plain text messages
        if not isinstance(message_meta, tuple) or len(message_meta) < 2:
            logger(f"ℹ️ [Ryan] Non-embed message, skipping")
            return [], 0

        title, description = message_meta[0], message_meta[1]

        # Cache check
        cache = get_parse_cache()
        cached = cache.get(message_meta, message_history)
        if cached is not None:
            stats = cache.get_stats()
            logger(f"⚡ [Ryan] CACHE HIT (hit rate: {stats['hit_rate_pct']}%)")
            return cached

        # Dispatch based on embed title
        title_upper = (title or "").strip().upper()
        desc = self._clean_description(description or "")
        color = None  # Color not available in message_meta tuple

        result = self._dispatch(title_upper, desc, color, logger)

        latency_ms = (time.monotonic() - start) * 1000

        # Inject metadata into results
        now = datetime.now(timezone.utc).isoformat()
        for entry in result:
            entry["channel_id"] = self.channel_id
            entry["received_ts"] = now

        # Log
        if result:
            actions = [r.get("action") for r in result]
            logger(f"📊 [Ryan] Parsed {len(result)} result(s): {actions} ({latency_ms:.1f}ms)")
        else:
            logger(f"ℹ️ [Ryan] No actionable result ({latency_ms:.1f}ms)")

        # Cache result
        out = (result, latency_ms)
        cache.set(message_meta, out, message_history)
        return out

    def _dispatch(self, title_upper, desc, color, logger):
        """Route to the correct parser based on embed title, with color fallback."""
        if title_upper == "ENTRY":
            return self._parse_entry(desc, logger)
        elif title_upper == "TRIM":
            return self._parse_trim(desc, logger)
        elif title_upper == "EXIT":
            return self._parse_exit(desc, logger)
        elif title_upper == "COMMENT":
            return []  # COMMENT embeds are not actionable in RHTBv5

        # Color fallback if title is unrecognized
        if color is not None:
            if color == self.COLOR_ENTRY:
                return self._parse_entry(desc, logger)
            elif color == self.COLOR_TRIM:
                return self._parse_trim(desc, logger)
            elif color == self.COLOR_EXIT:
                return self._parse_exit(desc, logger)

        logger(f"ℹ️ [Ryan] Unrecognized embed: title='{title_upper}'")
        return []

    # ─── ENTRY: Regex parse ────────────────────────────────────────────────

    def _parse_entry(self, desc, logger):
        """Parse ENTRY embed via regex. Filters out futures entries."""
        # Filter futures first
        if self._FUTURES_ENTRY.search(desc):
            logger(f"ℹ️ [Ryan] Ignoring futures ENTRY: {desc[:80]}")
            return []

        match = self._ENTRY_SPX.search(desc)
        if not match:
            logger(f"⚠️ [Ryan] ENTRY embed but no SPX pattern: {desc[:80]}")
            return []

        strike = int(match.group(1))
        opt_type = match.group(2).lower()
        price = float(match.group(3))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        logger(f"🟢 [Ryan] ENTRY: SPX ${strike}{opt_type} @ ${price:.2f}")

        return [{
            "action": "buy",
            "ticker": "SPX",
            "strike": strike,
            "type": "call" if opt_type == "c" else "put",
            "expiration": today,
            "price": price,
            "size": "full",
        }]

    # ─── TRIM: Title-only dispatch ─────────────────────────────────────────

    def _parse_trim(self, desc, logger):
        """TRIM embed — title alone triggers action."""
        logger(f"🟡 [Ryan] TRIM: {desc[:80]}")
        return [{
            "action": "trim",
            "ticker": "SPX",
            "price": "market",
        }]

    # ─── EXIT: Title-only dispatch ─────────────────────────────────────────

    def _parse_exit(self, desc, logger):
        """EXIT embed — title alone triggers action."""
        logger(f"🔴 [Ryan] EXIT: {desc[:80]}")
        return [{
            "action": "exit",
            "ticker": "SPX",
            "price": "market",
        }]

    # ─── Description Cleaning ──────────────────────────────────────────────

    @staticmethod
    def _clean_description(desc):
        """Strip bold markers, emojis, and collapse whitespace."""
        desc = desc.replace("**", "")
        desc = RyanParser._EMOJI_RE.sub("", desc)
        desc = re.sub(r"\s+", " ", desc).strip()
        return desc
