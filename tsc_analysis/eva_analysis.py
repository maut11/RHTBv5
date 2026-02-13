#!/usr/bin/env python3
"""
Eva Channel Analysis Script
Scrapes last 500 messages from Eva's channel for embed structure analysis.
Focuses on Open/Close/Update embed patterns.
"""

import asyncio
import csv
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, Any, List
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import discord
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Eva channel ID
EVA_CHANNEL_ID = 1072556084662902846  # Eva's live channel
MESSAGE_LIMIT = 500


class EvaAnalyzer:
    def __init__(self, output_dir: str = "tsc_analysis"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        # Discord setup
        self.discord_token = os.getenv("DISCORD_USER_TOKEN")
        if not self.discord_token:
            raise ValueError("DISCORD_USER_TOKEN not found in .env file")

        self.client = discord.Client()
        self.scraped_messages: List[Dict[str, Any]] = []

        # Setup event handlers
        self.client.event(self.on_ready)

    async def on_ready(self):
        """Called when Discord client is ready"""
        print(f"Discord client ready - logged in as {self.client.user}")
        await self.scrape_and_analyze()
        await self.client.close()

    async def scrape_and_analyze(self):
        """Main workflow: scrape, export, analyze embed patterns"""
        try:
            channel = self.client.get_channel(EVA_CHANNEL_ID)
            if not channel:
                print(f"Channel {EVA_CHANNEL_ID} not found or no access")
                return

            print(f"Scraping channel: #{channel.name} ({EVA_CHANNEL_ID})")
            print(f"Fetching last {MESSAGE_LIMIT} messages...")

            # Fetch messages (newest first)
            messages = []
            async for message in channel.history(limit=MESSAGE_LIMIT):
                msg_data = await self.parse_discord_message(message, channel)
                messages.append(msg_data)

                if len(messages) % 50 == 0:
                    print(f"  Scraped {len(messages)} messages...")

                await asyncio.sleep(0.05)  # Rate limiting

            # Reverse to chronological order (oldest first)
            messages.reverse()
            self.scraped_messages = messages
            print(f"Scraped {len(messages)} messages")

            # Export raw messages
            self.export_raw_messages()

            # Analyze embed patterns
            self.analyze_embed_patterns()

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()

    async def parse_discord_message(self, message: discord.Message, channel) -> Dict[str, Any]:
        """Parse a Discord message into structured data, focusing on embeds"""
        msg_data = {
            "message_id": str(message.id),
            "timestamp": message.created_at.isoformat(),
            "author_name": message.author.name,
            "author_id": str(message.author.id),
            "content": message.content,
            "has_embeds": len(message.embeds) > 0,
            "embed_count": len(message.embeds),
            "embeds": [],
        }

        # Extract embed details
        if message.embeds:
            for embed in message.embeds:
                embed_data = {
                    "title": embed.title,
                    "description": embed.description,
                    "color": embed.color.value if embed.color else None,
                    "url": embed.url,
                    "author_name": embed.author.name if embed.author else None,
                    "footer": embed.footer.text if embed.footer else None,
                    "fields": [],
                }
                # Extract fields
                for field in embed.fields:
                    embed_data["fields"].append({
                        "name": field.name,
                        "value": field.value,
                        "inline": field.inline,
                    })
                msg_data["embeds"].append(embed_data)

        return msg_data

    def export_raw_messages(self):
        """Export raw scraped messages to CSV"""
        output_file = self.output_dir / "eva_raw_messages.csv"
        print(f"\nExporting raw messages to {output_file}...")

        fieldnames = [
            "message_id", "timestamp", "author_name", "author_id", "content",
            "has_embeds", "embed_count", "embed_title", "embed_description",
            "embed_color", "embed_author", "embed_footer", "embed_fields_json"
        ]

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for msg in self.scraped_messages:
                # One row per embed (or one row with no embed data if no embeds)
                if msg["embeds"]:
                    for embed in msg["embeds"]:
                        row = {
                            "message_id": msg["message_id"],
                            "timestamp": msg["timestamp"],
                            "author_name": msg["author_name"],
                            "author_id": msg["author_id"],
                            "content": msg["content"][:200] if msg["content"] else "",
                            "has_embeds": True,
                            "embed_count": msg["embed_count"],
                            "embed_title": embed.get("title", ""),
                            "embed_description": (embed.get("description") or "")[:500],
                            "embed_color": embed.get("color", ""),
                            "embed_author": embed.get("author_name", ""),
                            "embed_footer": embed.get("footer", ""),
                            "embed_fields_json": json.dumps(embed.get("fields", [])),
                        }
                        writer.writerow(row)
                else:
                    row = {
                        "message_id": msg["message_id"],
                        "timestamp": msg["timestamp"],
                        "author_name": msg["author_name"],
                        "author_id": msg["author_id"],
                        "content": msg["content"][:200] if msg["content"] else "",
                        "has_embeds": False,
                        "embed_count": 0,
                        "embed_title": "",
                        "embed_description": "",
                        "embed_color": "",
                        "embed_author": "",
                        "embed_footer": "",
                        "embed_fields_json": "[]",
                    }
                    writer.writerow(row)

        print(f"Exported {len(self.scraped_messages)} messages")

    def analyze_embed_patterns(self):
        """Analyze embed patterns for Open/Close/Update"""
        print("\n" + "=" * 60)
        print("EVA CHANNEL EMBED ANALYSIS")
        print("=" * 60)

        total_messages = len(self.scraped_messages)
        embed_messages = [m for m in self.scraped_messages if m["has_embeds"]]
        non_embed_messages = [m for m in self.scraped_messages if not m["has_embeds"]]

        print(f"\nTotal Messages: {total_messages}")
        print(f"Messages with Embeds: {len(embed_messages)} ({100*len(embed_messages)/total_messages:.1f}%)")
        print(f"Messages without Embeds: {len(non_embed_messages)}")

        # Analyze embed titles
        title_counts = {}
        color_counts = {}
        author_counts = {}

        # Sample embeds by title for analysis
        title_samples = {}

        for msg in embed_messages:
            for embed in msg["embeds"]:
                title = embed.get("title") or "(no title)"
                color = embed.get("color")
                author = embed.get("author_name") or "(no author)"

                title_counts[title] = title_counts.get(title, 0) + 1
                if color:
                    color_counts[color] = color_counts.get(color, 0) + 1
                author_counts[author] = author_counts.get(author, 0) + 1

                # Store sample for each title type
                if title not in title_samples:
                    title_samples[title] = []
                if len(title_samples[title]) < 3:
                    title_samples[title].append({
                        "description": embed.get("description", "")[:300],
                        "color": color,
                        "fields": embed.get("fields", []),
                        "timestamp": msg["timestamp"],
                    })

        print(f"\n{'='*60}")
        print("EMBED TITLE DISTRIBUTION")
        print("=" * 60)
        sorted_titles = sorted(title_counts.items(), key=lambda x: x[1], reverse=True)
        for title, count in sorted_titles:
            pct = 100 * count / len(embed_messages) if embed_messages else 0
            print(f"  {title}: {count} ({pct:.1f}%)")

        print(f"\n{'='*60}")
        print("EMBED COLOR DISTRIBUTION")
        print("=" * 60)
        sorted_colors = sorted(color_counts.items(), key=lambda x: x[1], reverse=True)
        for color, count in sorted_colors:
            pct = 100 * count / len(embed_messages) if embed_messages else 0
            # Convert to hex for readability
            hex_color = f"#{color:06x}" if color else "None"
            print(f"  {hex_color} ({color}): {count} ({pct:.1f}%)")

        print(f"\n{'='*60}")
        print("EMBED AUTHOR DISTRIBUTION")
        print("=" * 60)
        sorted_authors = sorted(author_counts.items(), key=lambda x: x[1], reverse=True)
        for author, count in sorted_authors:
            pct = 100 * count / len(embed_messages) if embed_messages else 0
            print(f"  {author}: {count} ({pct:.1f}%)")

        print(f"\n{'='*60}")
        print("SAMPLE EMBEDS BY TITLE")
        print("=" * 60)
        for title, samples in title_samples.items():
            print(f"\n--- {title} ---")
            for i, sample in enumerate(samples[:2]):
                print(f"\n  Sample {i+1}:")
                print(f"    Color: #{sample['color']:06x}" if sample['color'] else "    Color: None")
                desc = sample['description'].replace('\n', ' ')[:200]
                print(f"    Description: {desc}...")
                if sample['fields']:
                    print(f"    Fields: {json.dumps(sample['fields'][:2])}")

        # Save analysis to file
        summary_file = self.output_dir / "eva_analysis_summary.txt"
        with open(summary_file, 'w') as f:
            f.write(f"Eva Channel Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"Total Messages: {total_messages}\n")
            f.write(f"Messages with Embeds: {len(embed_messages)}\n")
            f.write(f"Messages without Embeds: {len(non_embed_messages)}\n\n")

            f.write("Embed Title Distribution:\n")
            for title, count in sorted_titles:
                f.write(f"  {title}: {count}\n")

            f.write("\nEmbed Color Distribution:\n")
            for color, count in sorted_colors:
                hex_color = f"#{color:06x}" if color else "None"
                f.write(f"  {hex_color}: {count}\n")

            f.write("\nSample Embeds:\n")
            for title, samples in title_samples.items():
                f.write(f"\n--- {title} ---\n")
                for sample in samples[:2]:
                    f.write(f"  Color: #{sample['color']:06x}\n" if sample['color'] else "  Color: None\n")
                    f.write(f"  Description: {sample['description'][:300]}\n")
                    if sample['fields']:
                        f.write(f"  Fields: {json.dumps(sample['fields'])}\n")
                    f.write("\n")

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
    print("Eva Channel Analyzer")
    print("=" * 40)
    print(f"Channel ID: {EVA_CHANNEL_ID}")
    print(f"Message Limit: {MESSAGE_LIMIT}")
    print("=" * 40 + "\n")

    try:
        analyzer = EvaAnalyzer()
        asyncio.run(analyzer.start())
    except KeyboardInterrupt:
        print("\nCancelled by user")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
