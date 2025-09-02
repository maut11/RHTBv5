# channels/price_parser.py
from datetime import datetime, timezone
from .base_parser import BaseParser

class PriceParser(BaseParser):
    """A utility parser to extract contract details from a free-form text query."""
    def __init__(self, openai_client):
        # We don't need a real channel_id or full config for this utility parser
        config = {
            "name": "PriceParser",
            "model": "gpt-4o-2024-08-06", # Use a capable model for accuracy
            "color": 0x3498DB # A blue color for informational commands
        }
        # Pass a dummy channel_id; it won't be used for this command
        super().__init__(openai_client, channel_id=0, config=config)

    def build_prompt(self) -> str:
        """Builds a prompt specifically for extracting contract details from a query."""
        today = datetime.now(timezone.utc)
        current_year = today.year
        today_str = today.strftime('%Y-%m-%d')
        
        # The message meta will just be the raw string query from the user
        query_text = self._current_message_meta

        return f"""
You are an expert at extracting options contract details from a short, free-form text query.
Your ONLY job is to extract the ticker, strike, option type, and expiration date.

--- CURRENT DATE ---
Today: {today_str}
Year: {current_year}

--- DATE RULES ---
1.  For expiration dates, return them in MM-DD format (e.g., "01-16", "09-19"). Do NOT add years.
2.  If the query mentions "weekly" or "next week", assume it's for the coming Friday and return in MM-DD format.
3.  If the query mentions "monthly", assume it's for the third Friday of the specified month and return in MM-DD format.
4.  If no expiration is mentioned at all, assume it's a 0DTE trade. Return "0dte" as the expiration value.
5.  Examples: "1/16" → "01-16", "Sep 19" → "09-19", "0dte" → "0dte"

--- EXTRACTION RULES ---
-   `ticker`: The stock symbol (e.g., "SPY", "$APLD").
-   `strike`: The strike price (number).
-   `type`: The option type ("call" or "put"). 'c' or 'C' means "call", 'p' or 'P' means "put".
-   `expiration`: The expiration date in MM-DD format (or "0dte" for same-day trades).

--- EXAMPLES ---
- Query: "$APLD 15c Sep 19" -> {{"ticker": "APLD", "strike": 15, "type": "call", "expiration": "09-19"}}
- Query: "SPY 500 put this friday" -> (You would calculate the date for the upcoming Friday and format it as MM-DD)
- Query: "TSLA 900 weekly call" -> (You would calculate the date for the upcoming Friday and format it as MM-DD)
- Query: "QQQ 450p 10/20/25" -> {{"ticker": "QQQ", "strike": 450, "type": "put", "expiration": "10-20"}}
- Query: "IWM 200 call 0dte" -> {{"ticker": "IWM", "strike": 200, "type": "call", "expiration": "0dte"}}

If you cannot confidently extract all four key pieces of information (ticker, strike, type, expiration), return null.

--- QUERY TO PARSE ---
"{query_text}"

Return only a single, valid JSON object. Do not include explanations or markdown formatting.
"""

    def parse_message(self, message_meta, received_ts: datetime, logger):
        """
        Override BaseParser to handle utility parsing without action filtering.
        PriceParser doesn't need action fields - just contract details.
        """
        self._current_message_meta = message_meta
        prompt = self.build_prompt()
        parsed_data, latency_ms = self._call_openai(prompt, logger)

        total_latency = (datetime.now(timezone.utc) - received_ts).total_seconds() * 1000
        logger(f"⏱️ [{self.name}] Total processing latency: {total_latency:.2f} ms (OpenAI: {latency_ms:.2f} ms)")

        if parsed_data is None:
            return [], 0

        # Ensure we have a list
        results = parsed_data if isinstance(parsed_data, list) else [parsed_data]

        normalized_results = []
        now = datetime.now(timezone.utc).isoformat()
        
        for entry in results:
            if not isinstance(entry, dict):
                continue
            
            # For PriceParser, we don't need action fields - skip action processing entirely
            # Add minimal metadata
            entry["received_ts"] = now
            
            # Apply date normalization
            entry = self._normalize_entry(entry)
            
            normalized_results.append(entry)

        # Log summary - no action filtering needed for utility parser
        if normalized_results:
            logger(f"📊 [{self.name}] Parsed {len(normalized_results)} contract details")
        else:
            logger(f"ℹ️ [{self.name}] No contract details extracted")

        return normalized_results, latency_ms

    def parse_query(self, query: str, logger):
        """
        A simplified public method for this utility parser. It takes a raw query string,
        parses it, and returns the structured contract data.
        """
        # Use the overridden parse_message method
        received_ts = datetime.now(timezone.utc)
        parsed_results, _ = self.parse_message(query, received_ts, logger)
        
        # Return the first result if it exists, otherwise None
        return parsed_results[0] if parsed_results else None
