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
        self.model = config.get("model", "gpt-3.5-turbo")
        # --- ADDED: Store the color from the config, with a default fallback ---
        self.color = config.get("color", 7506394) # Default to gray if not specified
        self._current_message_meta = None

    @abstractmethod
    def build_prompt(self) -> str:
        """
        Builds the channel-specific prompt for the OpenAI API.
        Must be implemented by each subclass.
        """
        pass

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
            if content.startswith("```json"):
                content = content[7:-4]

            if not content:
                logger(f"❌ [{self.name}] Parsing failed: Empty response from OpenAI")
                return None, 0
            return json.loads(content), latency
        except json.JSONDecodeError as e:
            logger(f"❌ [{self.name}] JSON parse error: {e}\nRaw content: {content}")
            return None, 0
        except Exception as e:
            logger(f"❌ [{self.name}] OpenAI API error: {e}")
            return None, 0

    def parse_message(self, message_meta, received_ts: datetime, logger) -> tuple[list[dict], float]:
        """
        Main parsing method to be called by the bot.
        It orchestrates the prompt building, API call, and normalization.
        """
        self._current_message_meta = message_meta
        prompt = self.build_prompt()
        parsed_data, latency_ms = self._call_openai(prompt, logger)

        total_latency = (datetime.now(timezone.utc) - received_ts).total_seconds() * 1000
        logger(f"⏱️ [{self.name}] Total processing latency: {total_latency:.2f} ms (OpenAI: {latency_ms:.2f} ms)")


        if parsed_data is None:
            return [], 0

        results = parsed_data if isinstance(parsed_data, list) else [parsed_data]

        normalized_results = []
        now = datetime.now(timezone.utc).isoformat()
        for entry in results:
            if not isinstance(entry, dict) or entry.get("action") == "null":
                continue

            # Add common metadata
            entry["channel_id"] = self.channel_id
            entry["received_ts"] = now

            # Allow subclasses to perform custom normalization
            entry = self._normalize_entry(entry)
            normalized_results.append(entry)

        return normalized_results, latency_ms

    def _normalize_entry(self, entry: dict) -> dict:
        """
        Optional hook for subclasses to perform custom normalization.
        By default, it does nothing.
        """
        return entry