#!/usr/bin/env python3
"""
Test EvaParser (hybrid: regex + LLM) against scraped messages
"""

import csv
import json
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from openai import OpenAI

from channels.eva import EvaParser
from config import CHANNELS_CONFIG

# Load environment
load_dotenv()

# Eva channel ID
EVA_CHANNEL_ID = 1072556084662902846


def main():
    print("Testing EvaParser (Hybrid: Regex + LLM)")
    print("=" * 60)

    # Initialize OpenAI client
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    if not os.getenv("OPENAI_API_KEY"):
        print("Warning: No OPENAI_API_KEY - LLM calls will fail")
        openai_client = None

    # Initialize parser
    config = CHANNELS_CONFIG.get('Eva', {})
    config['name'] = 'Eva'
    parser = EvaParser(
        openai_client=openai_client,
        channel_id=EVA_CHANNEL_ID,
        config=config
    )

    # Load scraped messages
    csv_path = Path(__file__).parent / "eva_raw_messages.csv"
    if not csv_path.exists():
        print(f"Error: {csv_path} not found. Run eva_analysis.py first.")
        return

    results = {"buy": 0, "trim": 0, "exit": 0, "null": 0, "error": 0}
    method_counts = {"regex": 0, "llm": 0, "fallback": 0}
    total_embeds = 0
    actionable_samples = []
    logs = []

    def logger(msg):
        logs.append(msg)
        if "[Eva]" in msg and ("OPEN" in msg or "CLOSE" in msg or "LLM" in msg):
            print(f"  {msg}")

    # Test a subset for speed (Close alerts need LLM)
    max_to_test = 30  # Test first 30 actionable messages

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        tested = 0
        for row in reader:
            if not row.get("has_embeds") == "True":
                continue

            title = row.get("embed_title", "")
            description = row.get("embed_description", "")

            # Skip Update unless it has STC
            if title.strip().rstrip(":").upper() == "UPDATE":
                if "STC" not in description.upper():
                    results["null"] += 1
                    total_embeds += 1
                    continue

            total_embeds += 1

            # Limit LLM calls for testing
            if title.strip().upper() in ("CLOSE", "UPDATE:") and tested >= max_to_test:
                results["null"] += 1
                continue

            tested += 1
            logs.clear()

            # Create message_meta tuple
            message_meta = (title, description)

            # Parse
            try:
                trades, latency = parser.parse_message(
                    message_meta=message_meta,
                    received_ts=datetime.now(timezone.utc),
                    logger=logger,
                    message_history=None
                )

                # Track method used
                for log in logs:
                    if "(regex)" in log.lower():
                        method_counts["regex"] += 1
                    elif "(llm)" in log.lower():
                        method_counts["llm"] += 1
                    elif "fallback" in log.lower():
                        method_counts["fallback"] += 1

                if not trades:
                    results["null"] += 1
                else:
                    for trade in trades:
                        action = trade.get("action", "null")
                        if action in results:
                            results[action] += 1
                        else:
                            results["null"] += 1

                        # Store sample for review
                        if action in ("buy", "trim", "exit") and len(actionable_samples) < 20:
                            actionable_samples.append({
                                "title": title,
                                "description": description[:150],
                                "parsed": trade,
                                "method": "LLM" if any("(llm)" in l.lower() for l in logs) else "Regex"
                            })

            except Exception as e:
                results["error"] += 1
                print(f"  Error: {e}")

    print(f"\n{'='*60}")
    print("RESULTS")
    print("=" * 60)
    print(f"\nTotal Embeds: {total_embeds}")
    print(f"Tested with parsing: {tested}")
    print(f"\nAction Distribution:")
    for action, count in results.items():
        pct = 100 * count / total_embeds if total_embeds > 0 else 0
        print(f"  {action.upper():6s}: {count:3d} ({pct:.1f}%)")

    print(f"\nMethod Distribution:")
    for method, count in method_counts.items():
        print(f"  {method.upper():8s}: {count}")

    actionable = results["buy"] + results["trim"] + results["exit"]
    print(f"\nActionable Alerts: {actionable}")

    print(f"\n{'='*60}")
    print("SAMPLE PARSED TRADES")
    print("=" * 60)

    for sample in actionable_samples[:15]:
        parsed = sample["parsed"]
        action = parsed.get("action", "?")
        ticker = parsed.get("ticker", "?")
        strike = parsed.get("strike", "?")
        opt_type = parsed.get("type", "?")
        price = parsed.get("price", "?")
        exp = parsed.get("expiration", "?")
        method = sample.get("method", "?")

        type_char = opt_type[0] if opt_type and opt_type != "?" else "?"
        emoji = "🟢" if action == "buy" else ("🔴" if action == "exit" else "🟡")

        print(f"\n{emoji} [{action.upper()}] {ticker} {strike}{type_char} {exp} @ ${price} [{method}]")
        print(f"   Title: {sample['title']}")
        print(f"   Desc: {sample['description'][:80]}...")


if __name__ == "__main__":
    main()
