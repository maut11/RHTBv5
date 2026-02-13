#!/usr/bin/env python3
"""
Parse 100 most recent Eva alerts and save to CSV
"""

import csv
import json
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from openai import OpenAI

from channels.eva import EvaParser
from config import CHANNELS_CONFIG

load_dotenv()

EVA_CHANNEL_ID = 1072556084662902846


def main():
    print("Parsing 100 most recent Eva alerts")
    print("=" * 60)

    # Initialize OpenAI client
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Initialize parser
    config = CHANNELS_CONFIG.get('Eva', {})
    config['name'] = 'Eva'
    parser = EvaParser(
        openai_client=openai_client,
        channel_id=EVA_CHANNEL_ID,
        config=config
    )

    # Load scraped messages (most recent 100)
    csv_path = Path(__file__).parent / "eva_raw_messages.csv"
    if not csv_path.exists():
        print(f"Error: {csv_path} not found")
        return

    # Read all messages and take last 100
    all_messages = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_messages.append(row)

    # Take most recent 100 (last 100 in chronological order)
    recent_100 = all_messages[-100:]
    print(f"Processing {len(recent_100)} messages...")

    results = []

    def logger(msg):
        if "[Eva]" in msg:
            print(f"  {msg}")

    for i, row in enumerate(recent_100):
        if not row.get("has_embeds") == "True":
            continue

        title = row.get("embed_title", "")
        description = row.get("embed_description", "")
        timestamp = row.get("timestamp", "")
        message_id = row.get("message_id", "")

        message_meta = (title, description)

        try:
            trades, latency = parser.parse_message(
                message_meta=message_meta,
                received_ts=datetime.now(timezone.utc),
                logger=logger,
                message_history=None
            )

            if not trades:
                results.append({
                    "message_id": message_id,
                    "timestamp": timestamp,
                    "embed_title": title,
                    "embed_description": description[:200],
                    "action": "null",
                    "ticker": "",
                    "strike": "",
                    "type": "",
                    "expiration": "",
                    "price": "",
                    "size": "",
                    "method": "",
                    "latency_ms": f"{latency:.1f}"
                })
            else:
                for trade in trades:
                    results.append({
                        "message_id": message_id,
                        "timestamp": timestamp,
                        "embed_title": title,
                        "embed_description": description[:200],
                        "action": trade.get("action", ""),
                        "ticker": trade.get("ticker", ""),
                        "strike": trade.get("strike", ""),
                        "type": trade.get("type", ""),
                        "expiration": trade.get("expiration", ""),
                        "price": trade.get("price", ""),
                        "size": trade.get("size", ""),
                        "method": "LLM" if title.strip().rstrip(":").upper() in ("CLOSE", "UPDATE") else "Regex",
                        "latency_ms": f"{latency:.1f}"
                    })

        except Exception as e:
            print(f"  Error: {e}")
            results.append({
                "message_id": message_id,
                "timestamp": timestamp,
                "embed_title": title,
                "embed_description": description[:200],
                "action": "error",
                "ticker": "",
                "strike": "",
                "type": "",
                "expiration": "",
                "price": "",
                "size": "",
                "method": "",
                "latency_ms": "0"
            })

        if (i + 1) % 20 == 0:
            print(f"  Processed {i + 1}/{len(recent_100)}...")

    # Save to CSV
    output_path = Path(__file__).parent / "eva_parsed_100.csv"
    fieldnames = [
        "message_id", "timestamp", "embed_title", "embed_description",
        "action", "ticker", "strike", "type", "expiration", "price", "size",
        "method", "latency_ms"
    ]

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\n{'='*60}")
    print(f"Saved {len(results)} parsed results to {output_path}")

    # Summary
    actions = {}
    for r in results:
        action = r.get("action", "null")
        actions[action] = actions.get(action, 0) + 1

    print(f"\nAction Summary:")
    for action, count in sorted(actions.items()):
        print(f"  {action}: {count}")


if __name__ == "__main__":
    main()
