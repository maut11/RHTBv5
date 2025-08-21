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
1.  If a year is not specified (e.g., "Sep 19"), you MUST assume it is the current year, {current_year}.
2.  If the query mentions "weekly" or "next week", assume it's for the coming Friday.
3.  If the query mentions "monthly", assume it's for the third Friday of the specified month.
4.  If no expiration is mentioned at all, assume it's a 0DTE trade for today: {today_str}.
5.  The final `expiration` field in the JSON output must always be in YYYY-MM-DD format.

--- EXTRACTION RULES ---
-   `ticker`: The stock symbol (e.g., "SPY", "$APLD").
-   `strike`: The strike price (number).
-   `type`: The option type ("call" or "put"). 'c' or 'C' means "call", 'p' or 'P' means "put".
-   `expiration`: The expiration date in YYYY-MM-DD format.

--- EXAMPLES ---
- Query: "$APLD 15c Sep 19" -> {{"ticker": "APLD", "strike": 15, "type": "call", "expiration": "{current_year}-09-19"}}
- Query: "SPY 500 put this friday" -> (You would calculate the date for the upcoming Friday and format it as YYYY-MM-DD)
- Query: "TSLA 900 weekly call" -> (You would calculate the date for the upcoming Friday and format it as YYYY-MM-DD)
- Query: "QQQ 450p 10/20/25" -> {{"ticker": "QQQ", "strike": 450, "type": "put", "expiration": "2025-10-20"}}
- Query: "IWM 200 call 0dte" -> {{"ticker": "IWM", "strike": 200, "type": "call", "expiration": "{today_str}"}}

If you cannot confidently extract all four key pieces of information (ticker, strike, type, expiration), return null.

--- QUERY TO PARSE ---
"{query_text}"

Return only a single, valid JSON object. Do not include explanations or markdown formatting.
"""

    def parse_query(self, query: str, logger):
        """
        A simplified public method for this utility parser. It takes a raw query string,
        parses it, and returns the structured contract data.
        """
        # The base `parse_message` method handles the OpenAI call and returns a list of results.
        # For this command, we only expect one result.
        received_ts = datetime.now(timezone.utc)
        parsed_results, _ = self.parse_message(query, received_ts, logger)
        
        # Return the first result if it exists, otherwise None
        return parsed_results[0] if parsed_results else None
