# channels/base_parser.py
import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from openai import OpenAI

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
        self.color = config.get("color", 7506394) # Default to gray if not specified
        self._current_message_meta = None

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

    def _call_openai(self, prompt: str, logger) -> tuple[dict | list | None, float]:
        """Makes the API call to OpenAI and parses the JSON response."""
        start_time = datetime.now(timezone.utc)
        try:
            params = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}]
            }
            if self.model != "gpt-5-mini":
                params["temperature"] = 0
            
            response = self.client.chat.completions.create(**params)
            
            end_time = datetime.now(timezone.utc)
            latency = (end_time - start_time).total_seconds() * 1000
            logger(f"✅ [{self.name}] OpenAI API call successful. Latency: {latency:.2f} ms")

            content = response.choices[0].message.content.strip()
            
            # Handle markdown code blocks
            if content.startswith("```json"):
                content = content[7:]  # Remove ```json
                if content.endswith("```"):
                    content = content[:-3]  # Remove closing ```
            elif content.startswith("```"):
                content = content[3:]  # Remove opening ```
                if content.endswith("```"):
                    content = content[:-3]  # Remove closing ```

            if not content:
                logger(f"❌ [{self.name}] Parsing failed: Empty response from OpenAI")
                return None, 0
                
            # Parse JSON
            parsed_json = json.loads(content)
            
            # Log the raw parsed action for debugging
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
            
            return parsed_json, latency
            
        except json.JSONDecodeError as e:
            logger(f"❌ [{self.name}] JSON parse error: {e}\nRaw content: {content}")
            return None, 0
        except Exception as e:
            logger(f"❌ [{self.name}] OpenAI API error: {e}")
            return None, 0

    def parse_message(self, message_meta, received_ts: datetime, logger) -> tuple[list[dict], float]:
        """
        Main parsing method to be called by the bot.
        It orchestrates the prompt building, API call, normalization, and action standardization.
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
            
            normalized_results.append(entry)

        # Log summary of results
        if normalized_results:
            actions = [r.get('action', 'unknown') for r in normalized_results]
            logger(f"📊 [{self.name}] Parsed {len(normalized_results)} actionable results: {actions}")
        else:
            logger(f"ℹ️ [{self.name}] No actionable results from parsing")

        return normalized_results, latency_ms

    def _normalize_entry(self, entry: dict) -> dict:
        """
        Optional hook for subclasses to perform custom normalization.
        By default, it does nothing.
        Subclasses can override this to add channel-specific logic.
        """
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