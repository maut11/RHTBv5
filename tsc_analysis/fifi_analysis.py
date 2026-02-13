#!/usr/bin/env python3
"""
FiFi Channel Analysis Script
Scrapes last 50 messages from FiFi's channel, parses with FiFiParser,
exports to CSV, and analyzes trade patterns.
"""

import asyncio
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import discord
from dotenv import load_dotenv
from openai import OpenAI

from channels.fifi import FiFiParser
from config import CHANNELS_CONFIG

# Load environment variables
load_dotenv()

# FiFi channel ID
FIFI_CHANNEL_ID = 1368713891072315483  # FiFi's live channel
MESSAGE_LIMIT = 50
CONTEXT_WINDOW = 10


class FiFiAnalyzer:
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

        # Initialize FiFiParser
        config = CHANNELS_CONFIG.get('FiFi', {})
        config['name'] = 'FiFi'
        self.parser = FiFiParser(
            openai_client=self.openai_client,
            channel_id=FIFI_CHANNEL_ID,
            config=config
        )

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
            channel = self.client.get_channel(FIFI_CHANNEL_ID)
            if not channel:
                print(f"Channel {FIFI_CHANNEL_ID} not found or no access")
                return

            print(f"Scraping channel: #{channel.name} ({FIFI_CHANNEL_ID})")
            print(f"Fetching last {MESSAGE_LIMIT} messages...")

            # Fetch messages (newest first)
            messages = []
            async for message in channel.history(limit=MESSAGE_LIMIT):
                msg_data = await self.parse_discord_message(message, channel)
                messages.append(msg_data)

                if len(messages) % 10 == 0:
                    print(f"  Scraped {len(messages)} messages...")

                await asyncio.sleep(0.05)  # Rate limiting

            # Reverse to chronological order (oldest first)
            messages.reverse()
            self.scraped_messages = messages
            print(f"Scraped {len(messages)} messages")

            # Export raw messages first
            self.export_raw_messages()

            # Parse each message with FiFiParser using 10-message context
            print(f"\nParsing messages with FiFiParser (10-message context)...")
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

        # Check for embeds
        if message.embeds:
            for embed in message.embeds:
                embed_data = {
                    "title": embed.title,
                    "description": embed.description,
                    "url": embed.url,
                    "author": embed.author.name if embed.author else None,
                }
                msg_data["embeds"].append(embed_data)

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
        """Export raw scraped messages to CSV"""
        output_file = self.output_dir / "fifi_raw_messages.csv"
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

    async def parse_all_messages(self):
        """Parse all scraped messages with FiFiParser"""
        import logging
        logging.basicConfig(level=logging.WARNING)
        logger = logging.getLogger('fifi_analysis')

        for i, msg in enumerate(self.scraped_messages):
            # Skip empty messages
            if not msg["content"].strip():
                self.parsed_results.append({
                    "message_id": msg["message_id"],
                    "timestamp": msg["timestamp"],
                    "author": msg["author_name"],
                    "content": "",
                    "is_reply": msg["is_reply"],
                    "reply_context": "",
                    "is_edited": msg.get("is_edited", False),
                    "parsed_trades": [{"action": "null"}],
                    "trade_count": 0,
                    "parse_time_ms": 0
                })
                continue

            # Build history from previous messages
            history = []
            start_idx = max(0, i - CONTEXT_WINDOW)
            for j in range(start_idx, i):
                hist_msg = self.scraped_messages[j]
                ts = datetime.fromisoformat(hist_msg["timestamp"].replace('Z', '+00:00'))
                time_str = ts.strftime("%H:%M:%S")
                content = hist_msg['content'][:200]
                if content:
                    history.append(f"[{time_str}] {content}")

            # Build message meta
            reply_content = msg.get("reply_to_content", "")
            if msg["is_reply"] and reply_content and reply_content != "[Could not fetch]":
                message_meta = (msg["content"], reply_content)
            else:
                message_meta = msg["content"]

            # Get received timestamp
            try:
                received_ts = datetime.fromisoformat(msg["timestamp"].replace('Z', '+00:00'))
            except:
                received_ts = datetime.now(timezone.utc)

            # Parse with FiFiParser
            start_time = time.time()
            try:
                trades, latency = self.parser.parse_message(
                    message_meta=message_meta,
                    received_ts=received_ts,
                    logger=logger.info,
                    message_history=history
                )
                parse_time = (time.time() - start_time) * 1000

                if not trades:
                    trades = [{"action": "null"}]

            except Exception as e:
                print(f"  Error parsing message {i+1}: {e}")
                trades = [{"action": "error", "error": str(e)}]
                parse_time = 0

            # Store result
            self.parsed_results.append({
                "message_id": msg["message_id"],
                "timestamp": msg["timestamp"],
                "author": msg["author_name"],
                "content": msg["content"][:300],
                "is_reply": msg["is_reply"],
                "reply_context": reply_content[:200] if reply_content else "",
                "is_edited": msg.get("is_edited", False),
                "parsed_trades": trades,
                "trade_count": len([t for t in trades if t.get("action") not in ("null", "error")]),
                "parse_time_ms": parse_time
            })

            if (i + 1) % 10 == 0:
                print(f"  Parsed {i+1}/{len(self.scraped_messages)} messages...")

            await asyncio.sleep(0.1)

        print(f"Parsed all {len(self.parsed_results)} messages")

    def export_to_csv(self):
        """Export results to CSV"""
        output_file = self.output_dir / "fifi_parsed_50.csv"
        print(f"\nExporting to {output_file}...")

        fieldnames = [
            "message_id", "timestamp", "author", "content", "is_reply",
            "reply_context", "is_edited", "action", "ticker", "strike",
            "type", "price", "expiration", "size", "parse_time_ms", "raw_parsed"
        ]

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for result in self.parsed_results:
                trades = result["parsed_trades"]

                for trade in trades:
                    row = {
                        "message_id": result["message_id"],
                        "timestamp": result["timestamp"],
                        "author": result["author"],
                        "content": result["content"],
                        "is_reply": result["is_reply"],
                        "reply_context": result["reply_context"],
                        "is_edited": result["is_edited"],
                        "action": trade.get("action", "null"),
                        "ticker": trade.get("ticker", ""),
                        "strike": trade.get("strike", ""),
                        "type": trade.get("type", ""),
                        "price": trade.get("price", ""),
                        "expiration": trade.get("expiration", ""),
                        "size": trade.get("size", ""),
                        "parse_time_ms": result.get("parse_time_ms", 0),
                        "raw_parsed": json.dumps(trade)
                    }
                    writer.writerow(row)

        print(f"Exported to {output_file}")

    def analyze_results(self):
        """Analyze parsing results"""
        print("\n" + "="*60)
        print("FIFI CHANNEL ANALYSIS RESULTS")
        print("="*60)

        total_messages = len(self.parsed_results)

        action_counts = {"buy": 0, "trim": 0, "exit": 0, "null": 0, "error": 0}
        tickers = {}
        parse_times = []

        for result in self.parsed_results:
            if result.get("parse_time_ms"):
                parse_times.append(result["parse_time_ms"])

            for trade in result["parsed_trades"]:
                action = trade.get("action", "null")
                if action in action_counts:
                    action_counts[action] += 1
                else:
                    action_counts["null"] += 1

                ticker = trade.get("ticker", "")
                if ticker and action != "null":
                    tickers[ticker] = tickers.get(ticker, 0) + 1

        print(f"\nTotal Messages Analyzed: {total_messages}")
        print(f"\nAction Distribution:")
        for action, count in action_counts.items():
            pct = 100 * count / total_messages if total_messages > 0 else 0
            print(f"  - {action.upper():6s}: {count:3d} ({pct:.1f}%)")

        actionable = action_counts['buy'] + action_counts['trim'] + action_counts['exit']
        print(f"\nActionable Alerts: {actionable} ({100*actionable/total_messages:.1f}%)")

        if parse_times:
            avg_time = sum(parse_times) / len(parse_times)
            print(f"\nParse Time Stats:")
            print(f"  Average: {avg_time:.0f}ms")
            print(f"  Min: {min(parse_times):.0f}ms")
            print(f"  Max: {max(parse_times):.0f}ms")

        if tickers:
            print(f"\nTop Tickers:")
            sorted_tickers = sorted(tickers.items(), key=lambda x: x[1], reverse=True)[:10]
            for ticker, count in sorted_tickers:
                print(f"  - {ticker}: {count}")

        print(f"\n{'='*60}")
        print("ACTIONABLE TRADES DETECTED")
        print("="*60)

        for result in self.parsed_results:
            for trade in result["parsed_trades"]:
                action = trade.get("action", "null")
                if action in ("buy", "trim", "exit"):
                    ticker = trade.get("ticker", '?')
                    price = trade.get("price", '?')
                    strike = trade.get("strike", '')
                    opt_type = trade.get("type", '')
                    size = trade.get("size", 'full')

                    if action == "buy":
                        type_char = opt_type[0] if opt_type else '?'
                        print(f"\n[BUY] {ticker} {strike}{type_char} @ \${price} ({size})")
                    elif action == "trim":
                        print(f"\n[TRIM] {ticker} @ \${price}")
                    elif action == "exit":
                        print(f"\n[EXIT] {ticker} @ \${price}")

                    print(f"  Content: {result['content'][:80]}...")

        summary_file = self.output_dir / "fifi_analysis_summary.txt"
        with open(summary_file, 'w') as f:
            f.write(f"FiFi Channel Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write("="*60 + "\n\n")
            f.write(f"Total Messages: {total_messages}\n")
            f.write(f"Actionable Alerts: {actionable} ({100*actionable/total_messages:.1f}%)\n\n")
            f.write(f"Action Distribution:\n")
            for action, count in action_counts.items():
                f.write(f"  {action}: {count}\n")
            if parse_times:
                f.write(f"\nAvg Parse Time: {sum(parse_times)/len(parse_times):.0f}ms\n")

        print(f"\nAnalysis saved to {summary_file}")

    async def start(self):
        """Start the analyzer"""
        try:
            await self.client.start(self.discord_token)
        except discord.LoginFailure:
            print("Invalid Discord token")
        except Exception as e:
            print(f"Error: {e}")


def main():
    print("FiFi Channel Analyzer")
    print("="*40)
    print(f"Channel ID: {FIFI_CHANNEL_ID}")
    print(f"Message Limit: {MESSAGE_LIMIT}")
    print(f"Context Window: {CONTEXT_WINDOW} messages")
    print("="*40 + "\n")

    try:
        analyzer = FiFiAnalyzer()
        asyncio.run(analyzer.start())
    except KeyboardInterrupt:
        print("\nCancelled by user")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
