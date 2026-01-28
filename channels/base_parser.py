# channels/base_parser.py
import json
import hashlib
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone, date
from typing import Dict, List, Optional, Tuple, Union, Literal
from openai import OpenAI
import re
from pydantic import BaseModel, Field, field_validator, ValidationError


# ============= RESPONSE CACHING FOR LATENCY OPTIMIZATION =============

class ParseCache:
    """
    In-memory cache for parsed responses with TTL support.
    Uses normalized message content as key for exact matching.
    """
    def __init__(self, ttl_seconds: int = 300):  # 5 minute default TTL
        self._cache: Dict[str, Tuple[any, float]] = {}
        self._ttl = ttl_seconds
        self._hits = 0
        self._misses = 0

    def _normalize_message(self, message: str) -> str:
        """Normalize message for consistent cache keys."""
        if not message:
            return ""
        # Lowercase, strip whitespace, collapse multiple spaces
        return " ".join(str(message).lower().split())

    def _get_cache_key(self, message_meta, message_history: Optional[List[str]] = None) -> str:
        """Generate cache key from message metadata and history context."""
        if isinstance(message_meta, tuple):
            # For replies: combine both messages
            normalized = self._normalize_message(str(message_meta[0])) + "|" + self._normalize_message(str(message_meta[1]))
        else:
            normalized = self._normalize_message(str(message_meta))

        # Include message history in the key to avoid stale results
        # when same message appears in different conversation contexts
        if message_history:
            history_str = "|".join(self._normalize_message(msg) for msg in message_history)
            normalized = normalized + "||" + history_str

        # Hash for consistent key length
        return hashlib.md5(normalized.encode()).hexdigest()

    def get(self, message_meta, message_history: Optional[List[str]] = None) -> Optional[Tuple[List[Dict], float]]:
        """Get cached result if exists and not expired."""
        key = self._get_cache_key(message_meta, message_history)
        if key in self._cache:
            result, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                self._hits += 1
                return result
            else:
                # Expired, remove from cache
                del self._cache[key]
        self._misses += 1
        return None

    def set(self, message_meta, result: Tuple[List[Dict], float], message_history: Optional[List[str]] = None):
        """Cache a parsing result."""
        key = self._get_cache_key(message_meta, message_history)
        self._cache[key] = (result, time.time())

    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "hit_rate_pct": round(hit_rate, 1),
            "cache_size": len(self._cache)
        }

    def clear_expired(self):
        """Remove expired entries from cache."""
        current_time = time.time()
        expired_keys = [k for k, (_, ts) in self._cache.items() if current_time - ts >= self._ttl]
        for key in expired_keys:
            del self._cache[key]


# Global cache instance (shared across all parsers)
_parse_cache = ParseCache(ttl_seconds=300)


def get_parse_cache() -> ParseCache:
    """Get the global parse cache instance."""
    return _parse_cache


# ============= PYDANTIC SCHEMAS FOR ALERT VALIDATION =============

class BuyAlert(BaseModel):
    """Schema for BUY alerts - new position entries"""
    action: Literal["buy"]
    ticker: str
    strike: float
    type: Literal["call", "put"]
    expiration: str  # YYYY-MM-DD format
    price: float
    size: Literal["full", "half", "lotto"] = "full"

    @field_validator('ticker')
    @classmethod
    def normalize_ticker(cls, v):
        return v.upper().replace('$', '').strip()

    @field_validator('type', mode='before')
    @classmethod
    def normalize_option_type(cls, v):
        if isinstance(v, str):
            v_lower = v.lower().strip()
            if v_lower in ['c', 'call', 'calls']:
                return 'call'
            elif v_lower in ['p', 'put', 'puts']:
                return 'put'
        return v


class TrimAlert(BaseModel):
    """Schema for TRIM alerts - partial exits"""
    action: Literal["trim"]
    ticker: str
    strike: Optional[float] = None
    type: Optional[Literal["call", "put"]] = None
    expiration: Optional[str] = None
    price: Union[float, Literal["BE"]]

    @field_validator('ticker')
    @classmethod
    def normalize_ticker(cls, v):
        return v.upper().replace('$', '').strip()

    @field_validator('type', mode='before')
    @classmethod
    def normalize_option_type(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            v_lower = v.lower().strip()
            if v_lower in ['c', 'call', 'calls']:
                return 'call'
            elif v_lower in ['p', 'put', 'puts']:
                return 'put'
        return v


class ExitAlert(BaseModel):
    """Schema for EXIT alerts - full position closes"""
    action: Literal["exit"]
    ticker: str
    strike: Optional[float] = None
    type: Optional[Literal["call", "put"]] = None
    expiration: Optional[str] = None
    price: Union[float, Literal["BE"]]

    @field_validator('ticker')
    @classmethod
    def normalize_ticker(cls, v):
        return v.upper().replace('$', '').strip()

    @field_validator('type', mode='before')
    @classmethod
    def normalize_option_type(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            v_lower = v.lower().strip()
            if v_lower in ['c', 'call', 'calls']:
                return 'call'
            elif v_lower in ['p', 'put', 'puts']:
                return 'put'
        return v


class CommentaryAlert(BaseModel):
    """Schema for COMMENTARY/NULL alerts - non-actionable messages"""
    action: Literal["null"]
    message: Optional[str] = None


# Map action types to their schema classes
ALERT_SCHEMAS = {
    "buy": BuyAlert,
    "trim": TrimAlert,
    "exit": ExitAlert,
    "null": CommentaryAlert,
}


def validate_alert(data: dict, logger=print) -> Optional[BaseModel]:
    """
    Validate parsed alert data against the appropriate Pydantic schema.
    Returns validated model instance or None if validation fails.
    """
    action = data.get('action', '').lower()
    schema_class = ALERT_SCHEMAS.get(action)

    if not schema_class:
        logger(f"⚠️ Unknown action type: {action}")
        return None

    try:
        validated = schema_class(**data)
        return validated
    except ValidationError as e:
        logger(f"⚠️ Validation failed for {action} alert: {e.errors()}")
        return None

class BaseParser(ABC):
    """
    An abstract base class for channel message parsers.
    It handles the common logic of calling the OpenAI API, parsing JSON,
    and basic error handling, leaving channel-specific logic to subclasses.
    """
    def __init__(self, openai_client: OpenAI, channel_id: int, config: dict):
        self.client = openai_client
        self.channel_id = channel_id
        self.name = config["name"]
        self.model = config.get("model", "gpt-4o-2024-08-06")
        # Store the color from the config, with a default fallback
        self.color = config.get("color", 7506394)  # Default to gray if not specified
        self._current_message_meta = None
        self._message_history = []  # Recent messages for context

    @abstractmethod
    def build_prompt(self) -> str:
        """
        Builds the channel-specific prompt for the OpenAI API.
        Must be implemented by each subclass.
        """
        pass

    def _standardize_action(self, action: str) -> str:
        """
        Standardize action values across all parsers to ensure consistency.
        This prevents issues like 'entry' vs 'buy' causing trade execution failures.
        """
        if not action:
            return "null"
        
        # Convert to string and normalize
        action_lower = str(action).lower().strip()
        
        # Buy variations - all map to "buy"
        if action_lower in ["buy", "entry", "bto", "long", "open", "enter", "bought", 
                           "buying", "opening", "longing", "purchase", "purchasing"]:
            return "buy"
        
        # Trim variations - all map to "trim"
        elif action_lower in ["trim", "scale", "partial", "reduce", "take", "trimming",
                             "scaling", "partial_exit", "scale_out", "take_profit",
                             "tp", "partial_close", "half", "some"]:
            return "trim"
        
        # Exit variations - all map to "exit"
        elif action_lower in ["exit", "close", "stop", "stc", "sell", "out", "sold",
                             "exiting", "closing", "selling", "stopped", "full_exit",
                             "all_out", "done", "finished", "complete"]:
            return "exit"
        
        # Stop loss variations - also map to "exit" 
        elif action_lower in ["stop_loss", "sl", "stopped_out", "stop_hit", "stopped"]:
            return "exit"
        
        # Non-actionable variations - all map to "null"
        elif action_lower in ["null", "comment", "update", "watching", "none", "",
                             "monitor", "hold", "holding", "wait", "waiting",
                             "considering", "thinking", "maybe", "possibly"]:
            return "null"
        
        # If we don't recognize it, log it and return as-is (lowercase)
        else:
            print(f"⚠️ [{self.name}] Unrecognized action: '{action}' - returning as-is")
            return action_lower

    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if an error is retryable (transient)."""
        error_str = str(error).lower()
        # Rate limits, timeouts, server errors
        retryable_patterns = ['rate limit', '429', 'timeout', '500', '502', '503', '504', 'connection']
        return any(pattern in error_str for pattern in retryable_patterns)

    def _call_openai_with_retry(self, model: str, prompt: str, logger, max_retries: int = 3) -> Tuple[Optional[str], float, Dict]:
        """
        Make OpenAI API call with exponential backoff retry for transient errors.
        Returns (response_content, latency_ms, token_info) or (None, latency_ms, {}) on failure.
        """
        backoff_delays = [1, 2, 4]  # Exponential backoff: 1s, 2s, 4s
        total_latency = 0
        token_info = {}

        for attempt in range(max_retries):
            start_time = datetime.now(timezone.utc)
            try:
                params = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0
                }

                response = self.client.chat.completions.create(**params)

                end_time = datetime.now(timezone.utc)
                latency = (end_time - start_time).total_seconds() * 1000
                total_latency += latency

                # Extract token usage from response
                if hasattr(response, 'usage') and response.usage:
                    token_info = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                        "model": model
                    }

                content = response.choices[0].message.content.strip()
                return content, total_latency, token_info

            except Exception as e:
                end_time = datetime.now(timezone.utc)
                latency = (end_time - start_time).total_seconds() * 1000
                total_latency += latency

                if self._is_retryable_error(e) and attempt < max_retries - 1:
                    delay = backoff_delays[min(attempt, len(backoff_delays) - 1)]
                    logger(f"🔄 [{self.name}] Retryable error from {model}: {e}. Retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue
                else:
                    raise  # Re-raise non-retryable or final attempt errors

        return None, total_latency, {}

    def _call_openai(self, prompt: str, logger) -> Tuple[Optional[Union[Dict, List]], float]:
        """
        Makes the API call to OpenAI with fallback model strategy and retry logic.
        Tries gpt-4o-mini first for speed, falls back to configured model on failure.
        Includes exponential backoff retry for transient errors.
        """
        # Model fallback order: try fast model first, then configured model
        fast_model = "gpt-4o-mini"
        fallback_model = self.model  # Configured model (usually gpt-4o)
        models_to_try = [fast_model] if fast_model != fallback_model else [fallback_model]
        if fast_model != fallback_model:
            models_to_try.append(fallback_model)

        total_latency = 0
        last_error = None

        for model in models_to_try:
            try:
                # Call with retry logic (returns content, latency, token_info)
                content, latency, token_info = self._call_openai_with_retry(model, prompt, logger)
                total_latency += latency

                if not content:
                    logger(f"⚠️ [{self.name}] Empty response from {model}, trying fallback...")
                    continue

                # Parse JSON
                parsed_json = json.loads(content)

                # Validate response has required structure
                if not self._validate_response_structure(parsed_json):
                    logger(f"⚠️ [{self.name}] Invalid response structure from {model}, trying fallback...")
                    continue

                # Success! Log with latency and token tracking
                token_log = ""
                if token_info:
                    token_log = f" | Tokens: {token_info.get('prompt_tokens', 0)}→{token_info.get('completion_tokens', 0)} ({token_info.get('total_tokens', 0)} total)"
                logger(f"✅ [{self.name}] OpenAI call successful with {model}. Latency: {latency:.2f} ms{token_log}")

                # Log the raw parsed action for debugging
                self._log_parsed_actions(parsed_json, logger)

                return parsed_json, total_latency

            except json.JSONDecodeError as e:
                last_error = e
                logger(f"⚠️ [{self.name}] JSON parse error from {model}: {e}")
                continue
            except Exception as e:
                last_error = e
                logger(f"⚠️ [{self.name}] API error from {model}: {e}")
                continue

        # All models failed
        logger(f"❌ [{self.name}] All models failed. Last error: {last_error}")
        return None, total_latency

    def _validate_response_structure(self, parsed_json) -> bool:
        """Validate that the response has the required structure."""
        if isinstance(parsed_json, dict):
            # Must have an action field
            return 'action' in parsed_json
        elif isinstance(parsed_json, list):
            # If list, at least one item must have action
            return any(isinstance(item, dict) and 'action' in item for item in parsed_json)
        return False

    def _log_parsed_actions(self, parsed_json, logger):
        """Log the raw parsed actions for debugging."""
        if isinstance(parsed_json, dict):
            raw_action = parsed_json.get('action')
            if raw_action:
                logger(f"🔍 [{self.name}] Raw action from OpenAI: '{raw_action}'")
        elif isinstance(parsed_json, list):
            for item in parsed_json:
                if isinstance(item, dict):
                    raw_action = item.get('action')
                    if raw_action:
                        logger(f"🔍 [{self.name}] Raw action from OpenAI: '{raw_action}'")

    def parse_message(self, message_meta, received_ts: datetime, logger, message_history: Optional[List[str]] = None) -> Tuple[List[Dict], float]:
        """
        Main parsing method to be called by the bot.
        It orchestrates the prompt building, API call, normalization, and action standardization.

        Args:
            message_meta: Current message content (string or tuple for replies)
            received_ts: Timestamp when message was received
            logger: Logging function
            message_history: Optional list of recent messages for context (oldest first)
        """
        # Check cache first for duplicate messages
        cache = get_parse_cache()
        cached_result = cache.get(message_meta, message_history)
        if cached_result is not None:
            cache_stats = cache.get_stats()
            logger(f"⚡ [{self.name}] CACHE HIT - returning cached result (hit rate: {cache_stats['hit_rate_pct']}%)")
            return cached_result

        self._current_message_meta = message_meta
        self._message_history = message_history or []
        prompt = self.build_prompt()
        parsed_data, latency_ms = self._call_openai(prompt, logger)

        total_latency = (datetime.now(timezone.utc) - received_ts).total_seconds() * 1000
        cache_stats = cache.get_stats()
        logger(f"⏱️ [{self.name}] Total processing latency: {total_latency:.2f} ms (OpenAI: {latency_ms:.2f} ms) | Cache: {cache_stats['hit_rate_pct']}% hit rate ({cache_stats['hits']}/{cache_stats['total']})")

        if parsed_data is None:
            return [], 0

        # Ensure we have a list
        results = parsed_data if isinstance(parsed_data, list) else [parsed_data]

        normalized_results = []
        now = datetime.now(timezone.utc).isoformat()
        
        for entry in results:
            if not isinstance(entry, dict):
                continue
            
            # CRITICAL: Standardize the action field before any other processing
            if 'action' in entry:
                original_action = entry.get('action')
                standardized_action = self._standardize_action(original_action)
                entry['action'] = standardized_action
                
                # Log the standardization if it changed
                if original_action and original_action != standardized_action:
                    logger(f"🔄 [{self.name}] Action standardized: '{original_action}' → '{standardized_action}'")
            else:
                # If no action field, add one as "null"
                entry['action'] = "null"
                logger(f"⚠️ [{self.name}] No action field in parsed result, defaulting to 'null'")
            
            # Skip null actions
            if entry.get("action") == "null":
                logger(f"⏭️ [{self.name}] Skipping null action")
                continue

            # Add common metadata
            entry["channel_id"] = self.channel_id
            entry["received_ts"] = now

            # Allow subclasses to perform custom normalization
            # This happens AFTER action standardization
            entry = self._normalize_entry(entry)

            # Double-check action after subclass normalization
            # (in case subclass changed it)
            if 'action' in entry:
                entry['action'] = self._standardize_action(entry.get('action'))

            # Validate against Pydantic schema (for logging/debugging, non-blocking)
            validated = validate_alert(entry, logger)
            if validated:
                logger(f"✅ [{self.name}] Alert validated: {entry.get('action')} {entry.get('ticker', 'N/A')}")
                # Use validated data (normalized fields like ticker uppercase)
                entry.update(validated.model_dump(exclude_unset=True))
            else:
                logger(f"⚠️ [{self.name}] Alert validation failed, using raw parsed data")

            normalized_results.append(entry)

        # Log summary of results
        if normalized_results:
            actions = [r.get('action', 'unknown') for r in normalized_results]
            logger(f"📊 [{self.name}] Parsed {len(normalized_results)} actionable results: {actions}")
        else:
            logger(f"ℹ️ [{self.name}] No actionable results from parsing")

        # Cache the result for future duplicate messages
        result = (normalized_results, latency_ms)
        cache.set(message_meta, result, message_history)

        return result

    def _smart_year_detection(self, date_str: str, logger) -> str:
        """
        Convert MM-DD format dates to YYYY-MM-DD with intelligent year detection.
        If the date has already passed this year, assume it's for next year (LEAPS).
        Special handling for 0DTE (today's date).
        """
        if not date_str:
            return date_str
            
        # If already in YYYY-MM-DD format, return as-is
        if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
            return date_str
            
        # Handle 0DTE case - return today's date
        if date_str.lower() in ['0dte', 'today']:
            return datetime.now(timezone.utc).strftime('%Y-%m-%d')
            
        # Try to parse various date formats
        date_patterns = [
            # Full date formats with year
            (r'^(\d{1,2})/(\d{1,2})/(\d{4})$', 'MDY'),      # MM/DD/YYYY or M/D/YYYY
            (r'^(\d{1,2})-(\d{1,2})-(\d{4})$', 'MDY'),      # MM-DD-YYYY or M-D-YYYY
            (r'^(\d{4})-(\d{1,2})-(\d{1,2})$', 'YMD'),      # YYYY-MM-DD (already correct)
            # Date formats without year  
            (r'^(\d{1,2})-(\d{1,2})$', 'MD'),               # MM-DD or M-D
            (r'^(\d{1,2})/(\d{1,2})$', 'MD'),               # MM/DD or M/D
            # Month name formats
            (r'^([A-Za-z]{3,})\s+(\d{1,2})\s+(\d{4})$', 'MonDY'),  # "January 16 2026"
            (r'^([A-Za-z]{3,})\s+(\d{1,2})$', 'MonD'),             # "Jan 16"
        ]
        
        for pattern_info in date_patterns:
            pattern, format_type = pattern_info
            match = re.match(pattern, date_str)
            if match:
                try:
                    if format_type == 'YMD':
                        # YYYY-MM-DD format - already correct
                        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
                        return f"{year}-{month:02d}-{day:02d}"
                    
                    elif format_type == 'MDY':
                        # MM/DD/YYYY or MM-DD-YYYY format
                        month, day, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
                        target_date = datetime(year, month, day, tzinfo=timezone.utc)
                        return target_date.strftime('%Y-%m-%d')
                    
                    elif format_type == 'MD':
                        # MM/DD or MM-DD format (no year) - use smart year detection
                        month, day = int(match.group(1)), int(match.group(2))
                        
                        # Get current date info
                        now = datetime.now(timezone.utc)
                        current_year = now.year
                        
                        # Try to create date for current year
                        target_date = datetime(current_year, month, day, tzinfo=timezone.utc)
                        
                        # If the date has already passed this year, assume next year
                        if target_date.date() < now.date():
                            target_date = datetime(current_year + 1, month, day, tzinfo=timezone.utc)
                            logger(f"🗓️ [{self.name}] Date {date_str} has passed in {current_year}, using {current_year + 1}")
                        else:
                            logger(f"🗓️ [{self.name}] Date {date_str} is future in {current_year}, using {current_year}")
                            
                        return target_date.strftime('%Y-%m-%d')
                    
                    elif format_type == 'MonDY':
                        # "January 16 2026" format
                        month_name, day, year = match.group(1), int(match.group(2)), int(match.group(3))
                        month_num = datetime.strptime(month_name[:3], '%b').month
                        target_date = datetime(year, month_num, day, tzinfo=timezone.utc)
                        return target_date.strftime('%Y-%m-%d')
                    
                    elif format_type == 'MonD':
                        # "Jan 16" format (no year) - use smart year detection
                        month_name, day = match.group(1), int(match.group(2))
                        month_num = datetime.strptime(month_name[:3], '%b').month
                        
                        # Get current date info
                        now = datetime.now(timezone.utc)
                        current_year = now.year
                        
                        # Try to create date for current year
                        target_date = datetime(current_year, month_num, day, tzinfo=timezone.utc)
                        
                        # If the date has already passed this year, assume next year
                        if target_date.date() < now.date():
                            target_date = datetime(current_year + 1, month_num, day, tzinfo=timezone.utc)
                            logger(f"🗓️ [{self.name}] Date {date_str} has passed in {current_year}, using {current_year + 1}")
                        else:
                            logger(f"🗓️ [{self.name}] Date {date_str} is future in {current_year}, using {current_year}")
                            
                        return target_date.strftime('%Y-%m-%d')
                    
                except ValueError:
                    # Invalid date (e.g., Feb 30), return as-is
                    logger(f"⚠️ [{self.name}] Invalid date format: {date_str}")
                    return date_str
        
        # If no pattern matched, return as-is
        return date_str

    def _parse_monthly_expiration(self, expiration_str: str, logger) -> str:
        """
        Parse monthly expiration dates (e.g., "JAN 2026", "Jan 2026", "January 2026")
        to the third Friday of that month in YYYY-MM-DD format.
        """
        if not expiration_str:
            return expiration_str
            
        # Already in proper format
        if re.match(r'\d{4}-\d{2}-\d{2}', expiration_str):
            return expiration_str
            
        # Monthly expiration patterns
        month_patterns = [
            r'^(Jan|January|JAN)\s+(\d{4})$',
            r'^(Feb|February|FEB)\s+(\d{4})$',
            r'^(Mar|March|MAR)\s+(\d{4})$',
            r'^(Apr|April|APR)\s+(\d{4})$',
            r'^(May|MAY)\s+(\d{4})$',
            r'^(Jun|June|JUN)\s+(\d{4})$',
            r'^(Jul|July|JUL)\s+(\d{4})$',
            r'^(Aug|August|AUG)\s+(\d{4})$',
            r'^(Sep|September|SEP)\s+(\d{4})$',
            r'^(Oct|October|OCT)\s+(\d{4})$',
            r'^(Nov|November|NOV)\s+(\d{4})$',
            r'^(Dec|December|DEC)\s+(\d{4})$'
        ]
        
        month_map = {
            'jan': 1, 'january': 1,
            'feb': 2, 'february': 2,
            'mar': 3, 'march': 3,
            'apr': 4, 'april': 4,
            'may': 5,
            'jun': 6, 'june': 6,
            'jul': 7, 'july': 7,
            'aug': 8, 'august': 8,
            'sep': 9, 'september': 9,
            'oct': 10, 'october': 10,
            'nov': 11, 'november': 11,
            'dec': 12, 'december': 12
        }
        
        # Check for monthly patterns
        for pattern in month_patterns:
            match = re.match(pattern, expiration_str.strip(), re.IGNORECASE)
            if match:
                month_str = match.group(1).lower()
                year = int(match.group(2))
                month = month_map.get(month_str)
                
                if month:
                    # Calculate third Friday of the month
                    import calendar
                    cal = calendar.monthcalendar(year, month)
                    fridays = [week[4] for week in cal if week[4] != 0]  # Friday is index 4
                    
                    if len(fridays) >= 3:
                        third_friday = fridays[2]  # Third Friday (0-indexed)
                        result = f"{year}-{month:02d}-{third_friday:02d}"
                        logger(f"🗓️ [{self.name}] Monthly expiration parsed: '{expiration_str}' → '{result}'")
                        return result
                    else:
                        logger(f"⚠️ [{self.name}] Could not calculate third Friday for {month_str} {year}")
        
        # Not a monthly expiration, return as-is for other date parsing
        return expiration_str

    def _normalize_entry(self, entry: dict) -> dict:
        """
        Optional hook for subclasses to perform custom normalization.
        By default, it applies smart year detection to expiration dates as a FALLBACK.
        With the new LLM date parsing, expirations should already be in YYYY-MM-DD format.
        Subclasses can override this to add channel-specific logic.
        """
        # Apply expiration date parsing ONLY if not already in YYYY-MM-DD format
        if 'expiration' in entry and entry['expiration']:
            original_exp = str(entry['expiration']).strip()

            # Skip if already in YYYY-MM-DD format (LLM parsed correctly)
            if re.match(r'^\d{4}-\d{2}-\d{2}$', original_exp):
                print(f"✅ [{self.name}] Expiration already in YYYY-MM-DD format: {original_exp}")
                return entry

            # FALLBACK: Parse dates that LLM didn't convert correctly
            print(f"⚠️ [{self.name}] Expiration not in YYYY-MM-DD format, using fallback parsing: {original_exp}")

            # First try monthly expiration parsing (e.g., "JAN 2026")
            parsed_exp = self._parse_monthly_expiration(original_exp, print)

            # If not a monthly expiration, try regular date parsing
            if parsed_exp == original_exp:
                parsed_exp = self._smart_year_detection(original_exp, print)

            # Update if we successfully parsed it
            if parsed_exp != original_exp:
                entry['expiration'] = parsed_exp

        return entry

    def validate_parsed_data(self, entry: dict, logger) -> bool:
        """
        Validate that parsed data has minimum required fields based on action.
        This helps catch parsing issues early.
        """
        action = entry.get('action', '').lower()
        
        if action == 'buy':
            # Buy orders need ticker, strike, type, expiration, and price
            required = ['ticker', 'strike', 'type', 'expiration', 'price']
            missing = [f for f in required if not entry.get(f)]
            if missing:
                logger(f"⚠️ [{self.name}] Buy order missing fields: {missing}")
                return False
                
        elif action in ['trim', 'exit']:
            # Trim/Exit need at least ticker (other fields can be looked up)
            if not entry.get('ticker'):
                logger(f"⚠️ [{self.name}] {action.title()} order missing ticker")
                return False
                
        elif action == 'null':
            # Null actions are valid (non-actionable messages)
            return True
            
        return True

    def get_channel_info(self) -> dict:
        """
        Return information about this parser's channel configuration.
        Useful for debugging and status commands.
        """
        return {
            "name": self.name,
            "channel_id": self.channel_id,
            "model": self.model,
            "color": self.color
        }