#!/usr/bin/env python3
"""
Ian Channel Analysis Script
Scrapes last 100 messages from Ian's channel, parses with OpenAI using 10-message context,
exports to CSV, and analyzes trade patterns including stop loss updates.
"""

import asyncio
import csv
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import discord
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables
load_dotenv()

# Ian channel ID
IAN_CHANNEL_ID = 1457490555016839289
MESSAGE_LIMIT = 100
CONTEXT_WINDOW = 10  # Use last 10 messages as context


class IanAnalyzer:
    def __init__(self, output_dir: str = "tsc_analysis"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        # Discord setup
        self.discord_token = os.getenv("DISCORD_USER_TOKEN")
        if not self.discord_token:
            raise ValueError("DISCORD_USER_TOKEN not found in .env file")

        # OpenAI setup
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY not found in .env file")

        self.client = discord.Client()
        self.scraped_messages: List[Dict[str, Any]] = []
        self.parsed_results: List[Dict[str, Any]] = []

        # Setup event handlers
        self.client.event(self.on_ready)

    async def on_ready(self):
        """Called when Discord client is ready"""
        print(f"Discord client ready - logged in as {self.client.user}")
        await self.scrape_and_analyze()
        await self.client.close()

    async def scrape_and_analyze(self):
        """Main workflow: scrape, parse, export, analyze"""
        try:
            channel = self.client.get_channel(IAN_CHANNEL_ID)
            if not channel:
                print(f"Channel {IAN_CHANNEL_ID} not found or no access")
                return

            print(f"Scraping channel: #{channel.name} ({IAN_CHANNEL_ID})")
            print(f"Fetching last {MESSAGE_LIMIT} messages...")

            # Fetch messages (newest first)
            messages = []
            async for message in channel.history(limit=MESSAGE_LIMIT):
                msg_data = await self.parse_discord_message(message, channel)
                messages.append(msg_data)

                if len(messages) % 25 == 0:
                    print(f"  Scraped {len(messages)} messages...")

                await asyncio.sleep(0.05)  # Rate limiting

            # Reverse to chronological order (oldest first)
            messages.reverse()
            self.scraped_messages = messages
            print(f"Scraped {len(messages)} messages")

            # Export raw messages first (before parsing)
            self.export_raw_messages()

            # Parse each message with OpenAI using 10-message context
            print(f"\nParsing messages with OpenAI (10-message context)...")
            await self.parse_all_messages()

            # Export to CSV
            self.export_to_csv()

            # Analyze results
            self.analyze_results()

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()

    async def parse_discord_message(self, message: discord.Message, channel) -> Dict[str, Any]:
        """Parse a Discord message into structured data"""
        msg_data = {
            "message_id": str(message.id),
            "timestamp": message.created_at.isoformat(),
            "author_name": message.author.name,
            "author_display_name": message.author.display_name,
            "content": message.content,
            "is_reply": message.reference is not None,
            "reply_to_content": "",
            "is_forward": False,
            "forward_content": "",
            "is_edited": message.edited_at is not None,
            "edited_at": message.edited_at.isoformat() if message.edited_at else None,
            "embeds": [],
            "attachments": [a.url for a in message.attachments] if message.attachments else [],
        }

        # Check for embeds (forwards often show as embeds)
        if message.embeds:
            for embed in message.embeds:
                embed_data = {
                    "title": embed.title,
                    "description": embed.description,
                    "url": embed.url,
                    "author": embed.author.name if embed.author else None,
                }
                msg_data["embeds"].append(embed_data)

                # Detect forwards (embeds with author info)
                if embed.author:
                    msg_data["is_forward"] = True
                    msg_data["forward_content"] = embed.description or ""

        # Fetch reply context
        if message.reference and message.reference.message_id:
            try:
                replied = await channel.fetch_message(message.reference.message_id)
                msg_data["reply_to_content"] = replied.content[:500]
            except:
                msg_data["reply_to_content"] = "[Could not fetch]"

        return msg_data

    def export_raw_messages(self):
        """Export raw scraped messages to CSV for manual review"""
        output_file = self.output_dir / "ian_raw_messages.csv"

        print(f"\nExporting raw messages to {output_file}...")

        fieldnames = [
            "message_id", "timestamp", "author_name", "content",
            "is_reply", "reply_to_content", "is_forward", "forward_content",
            "is_edited", "edited_at", "embeds", "attachments"
        ]

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for msg in self.scraped_messages:
                row = {
                    "message_id": msg["message_id"],
                    "timestamp": msg["timestamp"],
                    "author_name": msg["author_name"],
                    "content": msg["content"][:500],
                    "is_reply": msg["is_reply"],
                    "reply_to_content": msg.get("reply_to_content", "")[:300],
                    "is_forward": msg.get("is_forward", False),
                    "forward_content": msg.get("forward_content", "")[:300],
                    "is_edited": msg.get("is_edited", False),
                    "edited_at": msg.get("edited_at", ""),
                    "embeds": json.dumps(msg.get("embeds", [])),
                    "attachments": json.dumps(msg.get("attachments", [])),
                }
                writer.writerow(row)

        print(f"Exported {len(self.scraped_messages)} raw messages")

    def build_ian_prompt(self, primary_message: str, context_message: str,
                         history: List[str], is_edited: bool) -> str:
        """Build Ian parser prompt with context - includes stop loss detection"""
        today = datetime.now(timezone.utc)
        current_year = today.year
        today_str = today.strftime('%Y-%m-%d')

        # Format history with time deltas
        history_text = "\n".join(history[-CONTEXT_WINDOW:]) if history else ""

        prompt = f"""You are a highly accurate data extraction assistant for option trading signals from a trader named Ian.
Your job is to extract EXECUTED trade actions and return a JSON array. Each distinct trade = one object.

--- NEGATIVE CONSTRAINTS (CHECK THESE FIRST) ---
If a message matches these patterns, return [{{"action": "null"}}]:

1. CONDITIONAL SETUPS / WATCHLISTS:
   "Looking for", "Watching", "If it breaks", "Will look to" -> "null"

2. INTENT / PLANS (not yet executed):
   "Plan:", "Going to", "will be", "might", "thinking about" -> "null"

3. BARE TICKER MENTIONS:
   Just a ticker with no action/price -> "null"

4. COMMENTARY / ANALYSIS:
   Market analysis, news, opinions without trade info -> "null"

--- ACTION DEFINITIONS ---
- "buy": EXECUTED new entry.
    - "in", "bought", "adding", "grabbed", "opening", "entered", "long"
- "trim": Partial take-profit.
    - "trim", "trimmed", "sold half", "sold some", "taking profits", "scaling out"
- "exit": Full close.
    - "out", "all out", "sold all", "closed", "stopped out", "flat"
- "stop_update": Stop loss level change (IMPORTANT - Ian emphasizes stop management)
    - "stop to", "move stop", "SL now", "new stop", "trailing stop", "stop at", "stops at"
- "null": Everything else.

--- STOP LOSS DETECTION (CRITICAL FOR IAN) ---
Ian frequently updates stop loss levels. Detect these patterns:
- "stop to $X" or "SL to $X" -> stop_update with stop_price
- "move stops to BE" or "stops at break even" -> stop_update with stop_price: "BE"
- "trailing stop at $X" -> stop_update with stop_price and trailing: true
- Include the TICKER if mentioned, resolve from context if not

--- OUTPUT FORMAT ---
Return a JSON array. Keys: lowercase snake_case.
- `action`: "buy", "trim", "exit", "stop_update", "null"
- `ticker`: Uppercase, no "$"
- `strike`: Number (for options)
- `type`: "call" or "put" (for options)
- `price`: Number, "BE", or "market"
- `expiration`: YYYY-MM-DD
- `size`: "full" (default), "half", "quarter", "lotto"
- `stop_price`: Number or "BE" (for stop_update actions)
- `trailing`: true/false (for trailing stops)

--- DATE RULES ---
Today: {today_str}. Year: {current_year}.
- "0dte"/"today" -> "{today_str}"
- "weekly"/"this week" -> Friday of current week
- "next week" -> Friday of next week
- Dates without year: use {current_year} if future, {current_year + 1} if passed

--- FEW-SHOT EXAMPLES ---

**BUY:**
"In SPY 600c 2/14 @ $2.50"
-> [{{"action": "buy", "ticker": "SPY", "strike": 600, "type": "call", "expiration": "{current_year}-02-14", "price": 2.50, "size": "full"}}]

**TRIM:**
"Trimmed half SPY calls at $4.00"
-> [{{"action": "trim", "ticker": "SPY", "type": "call", "price": 4.00, "size": "half"}}]

**EXIT:**
"All out TSLA, closed at $1.80"
-> [{{"action": "exit", "ticker": "TSLA", "price": 1.80}}]

**STOP UPDATE:**
"Moving stop to $3.00 on SPY calls"
-> [{{"action": "stop_update", "ticker": "SPY", "type": "call", "stop_price": 3.00}}]

**STOP TO BREAKEVEN:**
"Stops to BE on NVDA"
-> [{{"action": "stop_update", "ticker": "NVDA", "stop_price": "BE"}}]

**NULL (watchlist):**
"Watching AAPL for a breakout above $180"
-> [{{"action": "null"}}]

--- MESSAGE METADATA ---
IS_EDITED: {str(is_edited).lower()}
NOTE: If IS_EDITED is true, still parse but flag for review (edits should be logged but not traded).

--- MESSAGE TO PARSE ---
PRIMARY: "{primary_message}"
"""
        if context_message:
            prompt += f'\nREPLYING TO: "{context_message}"'

        if history_text:
            prompt += f'''

--- RECENT HISTORY (last {CONTEXT_WINDOW} messages, oldest first) ---
{history_text}

NOTE: Parse ONLY the PRIMARY message. History is context only (use to resolve tickers/strikes if missing).
'''

        return prompt

    async def parse_all_messages(self):
        """Parse all scraped messages with OpenAI"""
        for i, msg in enumerate(self.scraped_messages):
            # Build history from previous messages
            history = []
            start_idx = max(0, i - CONTEXT_WINDOW)
            for j in range(start_idx, i):
                hist_msg = self.scraped_messages[j]
                ts = datetime.fromisoformat(hist_msg["timestamp"].replace('Z', '+00:00'))
                time_str = ts.strftime("%H:%M:%S")
                content = hist_msg['content'][:200]
                # Include edit marker in history
                if hist_msg.get("is_edited"):
                    content = f"[EDITED] {content}"
                history.append(f"[{time_str}] {content}")

            # Build prompt
            prompt = self.build_ian_prompt(
                primary_message=msg["content"],
                context_message=msg.get("reply_to_content", ""),
                history=history,
                is_edited=msg.get("is_edited", False)
            )

            # Call OpenAI
            try:
                response = self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0
                )

                result_text = response.choices[0].message.content
                parsed = json.loads(result_text)

                # Handle both array and single object responses
                if isinstance(parsed, dict):
                    if "trades" in parsed:
                        trades = parsed["trades"]
                    elif "action" in parsed:
                        trades = [parsed]
                    else:
                        trades = [{"action": "null"}]
                elif isinstance(parsed, list):
                    trades = parsed
                else:
                    trades = [{"action": "null"}]

            except Exception as e:
                print(f"  Error parsing message {i+1}: {e}")
                trades = [{"action": "error", "error": str(e)}]

            # Store result
            self.parsed_results.append({
                "message_id": msg["message_id"],
                "timestamp": msg["timestamp"],
                "author": msg["author_name"],
                "content": msg["content"][:300],
                "is_reply": msg["is_reply"],
                "reply_context": msg.get("reply_to_content", "")[:200],
                "is_edited": msg.get("is_edited", False),
                "is_forward": msg.get("is_forward", False),
                "parsed_trades": trades,
                "trade_count": len([t for t in trades if t.get("action") not in ("null", "error")])
            })

            if (i + 1) % 10 == 0:
                print(f"  Parsed {i+1}/{len(self.scraped_messages)} messages...")

            await asyncio.sleep(0.1)  # Rate limiting

        print(f"Parsed all {len(self.parsed_results)} messages")

    def export_to_csv(self):
        """Export results to CSV"""
        output_file = self.output_dir / f"ian_parsed_{MESSAGE_LIMIT}.csv"

        print(f"\nExporting to {output_file}...")

        fieldnames = [
            "message_id", "timestamp", "author", "content", "is_reply",
            "reply_context", "is_edited", "is_forward", "action", "ticker", "strike",
            "type", "price", "expiration", "size", "stop_price", "trailing",
            "trade_count", "raw_parsed"
        ]

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for result in self.parsed_results:
                trades = result["parsed_trades"]

                # Write one row per trade (or one row for null)
                for trade in trades:
                    row = {
                        "message_id": result["message_id"],
                        "timestamp": result["timestamp"],
                        "author": result["author"],
                        "content": result["content"],
                        "is_reply": result["is_reply"],
                        "reply_context": result["reply_context"],
                        "is_edited": result["is_edited"],
                        "is_forward": result["is_forward"],
                        "action": trade.get("action", "null"),
                        "ticker": trade.get("ticker", ""),
                        "strike": trade.get("strike", ""),
                        "type": trade.get("type", ""),
                        "price": trade.get("price", ""),
                        "expiration": trade.get("expiration", ""),
                        "size": trade.get("size", ""),
                        "stop_price": trade.get("stop_price", ""),
                        "trailing": trade.get("trailing", ""),
                        "trade_count": result["trade_count"],
                        "raw_parsed": json.dumps(trade)
                    }
                    writer.writerow(row)

        print(f"Exported to {output_file}")

    def analyze_results(self):
        """Analyze parsing results"""
        print("\n" + "="*60)
        print("IAN CHANNEL ANALYSIS RESULTS")
        print("="*60)

        total_messages = len(self.parsed_results)

        # Count by action type
        action_counts = {"buy": 0, "trim": 0, "exit": 0, "stop_update": 0, "null": 0, "error": 0}
        tickers = {}
        buy_details = []
        trim_exit_details = []
        stop_updates = []
        edited_messages = []

        for result in self.parsed_results:
            if result.get("is_edited"):
                edited_messages.append(result)

            for trade in result["parsed_trades"]:
                action = trade.get("action", "null")
                if action in action_counts:
                    action_counts[action] += 1
                else:
                    action_counts["null"] += 1

                ticker = trade.get("ticker", "")
                if ticker and action != "null":
                    tickers[ticker] = tickers.get(ticker, 0) + 1

                if action == "buy":
                    buy_details.append({
                        "ticker": ticker,
                        "strike": trade.get("strike"),
                        "type": trade.get("type"),
                        "price": trade.get("price"),
                        "expiration": trade.get("expiration"),
                        "size": trade.get("size", "full"),
                        "timestamp": result["timestamp"],
                        "content": result["content"][:100]
                    })
                elif action in ("trim", "exit"):
                    trim_exit_details.append({
                        "action": action,
                        "ticker": ticker,
                        "price": trade.get("price"),
                        "timestamp": result["timestamp"],
                        "content": result["content"][:100]
                    })
                elif action == "stop_update":
                    stop_updates.append({
                        "ticker": ticker,
                        "stop_price": trade.get("stop_price"),
                        "trailing": trade.get("trailing", False),
                        "timestamp": result["timestamp"],
                        "content": result["content"][:100]
                    })

        # Print summary
        print(f"\nTotal Messages Analyzed: {total_messages}")
        print(f"\nAction Distribution:")
        print(f"  - BUY:         {action_counts['buy']:3d} ({100*action_counts['buy']/total_messages:.1f}%)")
        print(f"  - TRIM:        {action_counts['trim']:3d} ({100*action_counts['trim']/total_messages:.1f}%)")
        print(f"  - EXIT:        {action_counts['exit']:3d} ({100*action_counts['exit']/total_messages:.1f}%)")
        print(f"  - STOP_UPDATE: {action_counts['stop_update']:3d} ({100*action_counts['stop_update']/total_messages:.1f}%)")
        print(f"  - NULL:        {action_counts['null']:3d} ({100*action_counts['null']/total_messages:.1f}%)")
        print(f"  - ERROR:       {action_counts['error']:3d}")

        actionable = action_counts['buy'] + action_counts['trim'] + action_counts['exit'] + action_counts['stop_update']
        print(f"\nActionable Alerts: {actionable} ({100*actionable/total_messages:.1f}%)")

        # Edited messages analysis
        print(f"\n--- EDITED MESSAGES ---")
        print(f"Total Edited: {len(edited_messages)} ({100*len(edited_messages)/total_messages:.1f}%)")
        if edited_messages:
            print("Sample edited messages:")
            for i, msg in enumerate(edited_messages[:5]):
                print(f"  {i+1}. [{msg['timestamp'][:19]}] {msg['content'][:80]}...")

        # Stop loss analysis (key for Ian)
        print(f"\n--- STOP LOSS MANAGEMENT (Ian's emphasis) ---")
        print(f"Stop Updates Detected: {len(stop_updates)}")
        if stop_updates:
            be_stops = [s for s in stop_updates if s.get("stop_price") == "BE"]
            trailing_stops = [s for s in stop_updates if s.get("trailing")]
            print(f"  - Breakeven stops: {len(be_stops)}")
            print(f"  - Trailing stops:  {len(trailing_stops)}")
            print(f"  - Fixed price stops: {len(stop_updates) - len(be_stops) - len(trailing_stops)}")

            print("\nSample stop updates:")
            for i, stop in enumerate(stop_updates[:5]):
                print(f"  {i+1}. {stop['ticker']} -> SL: {stop['stop_price']} | {stop['content'][:60]}...")

        # Top tickers
        if tickers:
            print(f"\nTop Tickers Traded:")
            sorted_tickers = sorted(tickers.items(), key=lambda x: x[1], reverse=True)[:10]
            for ticker, count in sorted_tickers:
                print(f"  - {ticker}: {count}")

        # Trade details
        if buy_details:
            print(f"\n--- BUY SIGNALS ({len(buy_details)}) ---")

            # Type distribution
            types = {"call": 0, "put": 0, "unknown": 0}
            for buy in buy_details:
                t = (buy.get("type") or "unknown").lower()
                if t in types:
                    types[t] += 1
                else:
                    types["unknown"] += 1

            print(f"  Option Type: Calls={types['call']}, Puts={types['put']}, Unknown={types['unknown']}")

            print(f"\n  Sample Buy Signals:")
            for i, buy in enumerate(buy_details[:5]):
                opt_type = (buy.get('type') or '?')[0] if buy.get('type') else '?'
                print(f"    {i+1}. {buy['ticker']} ${buy.get('strike', '?')}{opt_type} @ ${buy.get('price', '?')} ({buy.get('size', 'full')})")

        if trim_exit_details:
            print(f"\n--- TRIM/EXIT SIGNALS ({len(trim_exit_details)}) ---")
            trims = [t for t in trim_exit_details if t['action'] == 'trim']
            exits = [t for t in trim_exit_details if t['action'] == 'exit']
            print(f"  - Trims: {len(trims)}")
            print(f"  - Exits: {len(exits)}")

        # Efficiency assessment
        print("\n" + "-"*60)
        print("COPY TRADE EFFICIENCY ASSESSMENT")
        print("-"*60)

        actionable_rate = 100 * actionable / total_messages if total_messages > 0 else 0

        if actionable_rate >= 25:
            efficiency = "HIGH"
            recommendation = "Ian's channel has a high signal-to-noise ratio. Copy trading is viable."
        elif actionable_rate >= 15:
            efficiency = "MEDIUM"
            recommendation = "Moderate signal rate. Copy trading possible with stop management integration."
        else:
            efficiency = "LOW"
            recommendation = "Low actionable signal rate. Copy trading may not be efficient."

        print(f"\nSignal Density: {actionable_rate:.1f}% actionable")
        print(f"Efficiency Rating: {efficiency}")
        print(f"\nRecommendation: {recommendation}")

        # Stop loss ratio
        if buy_details:
            stop_ratio = len(stop_updates) / len(buy_details) if buy_details else 0
            print(f"\nStop Updates per Buy: {stop_ratio:.2f}")
            if stop_ratio > 0.5:
                print("  -> Ian actively manages stops - consider implementing stop tracking")

        # Save analysis to file
        analysis_file = self.output_dir / "ian_analysis_summary.txt"
        with open(analysis_file, 'w') as f:
            f.write(f"Ian Channel Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write("="*60 + "\n\n")
            f.write(f"Total Messages: {total_messages}\n")
            f.write(f"Actionable Alerts: {actionable} ({actionable_rate:.1f}%)\n\n")
            f.write(f"Action Distribution:\n")
            for action, count in action_counts.items():
                f.write(f"  {action}: {count}\n")
            f.write(f"\nEdited Messages: {len(edited_messages)}\n")
            f.write(f"Stop Updates: {len(stop_updates)}\n")
            f.write(f"\nEfficiency: {efficiency}\n")
            f.write(f"Recommendation: {recommendation}\n")

        print(f"\nAnalysis saved to {analysis_file}")

    async def start(self):
        """Start the analyzer"""
        try:
            await self.client.start(self.discord_token)
        except discord.LoginFailure:
            print("Invalid Discord token")
        except Exception as e:
            print(f"Error: {e}")


def main():
    print("Ian Channel Analyzer")
    print("="*40)
    print(f"Channel ID: {IAN_CHANNEL_ID}")
    print(f"Message Limit: {MESSAGE_LIMIT}")
    print(f"Context Window: {CONTEXT_WINDOW} messages")
    print("="*40 + "\n")

    try:
        analyzer = IanAnalyzer()
        asyncio.run(analyzer.start())
    except KeyboardInterrupt:
        print("\nCancelled by user")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
