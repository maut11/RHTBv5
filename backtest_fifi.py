#!/usr/bin/env python3
"""Backtest FiFiParser against all 1000 scraped messages from fifi_messages.csv"""
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from collections import Counter, defaultdict
from dotenv import load_dotenv

load_dotenv()

from openai import OpenAI
from channels.fifi import FiFiParser

# ─── Config ───
CSV_PATH = "fifi_messages.csv"
OUTPUT_PATH = "fifi_backtest_results.json"
PROGRESS_INTERVAL = 50  # Print progress every N messages
FIFI_USERNAME = "sauced2002"

def load_messages(csv_path):
    """Load messages from CSV in chronological order (oldest first)."""
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    # CSV is newest-first, reverse for chronological order
    rows.reverse()
    return rows

def build_message_history(messages, current_idx, limit=10):
    """Build message history from the previous N messages, formatted like main.py does."""
    history = []
    start = max(0, current_idx - limit)
    for i in range(start, current_idx):
        msg = messages[i]
        content = msg.get("content", "").strip()
        if not content:
            continue
        # Format like main.py: [HH:MM:SS] content (truncated to 200 chars)
        try:
            ts = datetime.fromisoformat(msg["timestamp"])
            ts_str = ts.strftime("%H:%M:%S")
        except Exception:
            ts_str = "00:00:00"
        truncated = content[:200]
        history.append(f"[{ts_str}] {truncated}")
    return history

def build_message_meta(msg):
    """Build message_meta like main.py _extract_message_content does."""
    content = msg.get("content", "").strip()
    is_reply = msg.get("is_reply", "").strip().lower() == "true"
    reply_content = msg.get("reply_to_content", "").strip()

    if is_reply and reply_content:
        return (content, reply_content)
    return content

def run_backtest():
    print("=" * 70)
    print("FiFi Parser Backtest - 1000 Scraped Messages")
    print("=" * 70)

    # Initialize
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not found in .env")
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    parser = FiFiParser(client, 1368713891072315483, {
        "name": "FiFi",
        "model": "gpt-4o-mini",
        "color": 15277667
    })

    messages = load_messages(CSV_PATH)
    total = len(messages)
    print(f"Loaded {total} messages from {CSV_PATH}")
    print(f"Date range: {messages[0]['timestamp'][:10]} to {messages[-1]['timestamp'][:10]}")
    print()

    # Track results
    results = []
    action_counts = Counter()
    errors = []
    api_calls = 0
    total_latency = 0
    skipped = 0

    start_time = time.time()

    for idx, msg in enumerate(messages):
        # Only parse FiFi's messages
        if msg.get("author_name") != FIFI_USERNAME:
            skipped += 1
            continue

        content = msg.get("content", "").strip()
        if not content:
            skipped += 1
            continue

        # Build context
        message_meta = build_message_meta(msg)
        message_history = build_message_history(messages, idx, limit=10)

        # Simple logger
        def log_func(text):
            pass  # Suppress parse logs during backtest

        try:
            parsed_results, latency_ms = parser.parse_message(
                message_meta,
                datetime.now(timezone.utc),
                log_func,
                message_history=message_history
            )
            api_calls += 1
            total_latency += latency_ms

            # Record results
            for pr in parsed_results:
                action = pr.get("action", "unknown")
                action_counts[action] += 1

            result_entry = {
                "idx": idx,
                "message_id": msg.get("message_id", ""),
                "timestamp": msg.get("timestamp", ""),
                "content": content[:300],
                "is_reply": msg.get("is_reply", "False"),
                "reply_to_content": msg.get("reply_to_content", "")[:200],
                "parsed": parsed_results,
                "latency_ms": latency_ms,
                "has_alert_ping": "<@&1369304547356311564>" in content
            }
            results.append(result_entry)

        except Exception as e:
            errors.append({
                "idx": idx,
                "message_id": msg.get("message_id", ""),
                "content": content[:200],
                "error": str(e)
            })
            api_calls += 1

        # Progress reporting
        if (idx + 1) % PROGRESS_INTERVAL == 0:
            elapsed = time.time() - start_time
            rate = api_calls / elapsed if elapsed > 0 else 0
            print(f"[{idx+1}/{total}] API calls: {api_calls}, "
                  f"Actions: {dict(action_counts)}, "
                  f"Errors: {len(errors)}, "
                  f"Rate: {rate:.1f} calls/sec")

    elapsed = time.time() - start_time

    # ─── Summary ───
    print()
    print("=" * 70)
    print("BACKTEST RESULTS")
    print("=" * 70)
    print(f"Total messages:     {total}")
    print(f"Skipped (non-FiFi): {skipped}")
    print(f"Parsed:             {len(results)}")
    print(f"API calls:          {api_calls}")
    print(f"Errors:             {len(errors)}")
    print(f"Elapsed time:       {elapsed:.1f}s")
    print(f"Avg latency:        {total_latency / api_calls:.0f}ms" if api_calls else "N/A")
    print()
    print("─── Action Distribution ───")
    total_actions = sum(action_counts.values())
    for action in ["buy", "trim", "exit", "null"]:
        count = action_counts.get(action, 0)
        pct = (count / total_actions * 100) if total_actions else 0
        print(f"  {action:8s}: {count:4d}  ({pct:5.1f}%)")
    # Any unexpected actions
    for action, count in action_counts.items():
        if action not in ("buy", "trim", "exit", "null"):
            print(f"  {action:8s}: {count:4d}  (UNEXPECTED)")
    print(f"  {'TOTAL':8s}: {total_actions:4d}")

    # ─── Research comparison ───
    print()
    print("─── Comparison to Research Findings ───")
    print("Research expected: ~55 buys, ~154 trims, ~73 exits, ~702 null/commentary")
    print(f"Backtest got:      {action_counts.get('buy', 0)} buys, "
          f"{action_counts.get('trim', 0)} trims, "
          f"{action_counts.get('exit', 0)} exits, "
          f"{action_counts.get('null', 0)} null")

    # ─── Alert ping correlation ───
    ping_actions = Counter()
    no_ping_actions = Counter()
    for r in results:
        has_ping = r.get("has_alert_ping", False)
        for pr in r["parsed"]:
            a = pr.get("action", "null")
            if has_ping:
                ping_actions[a] += 1
            else:
                no_ping_actions[a] += 1
    print()
    print("─── Alert Ping Correlation ───")
    print(f"  With ping:    {dict(ping_actions)}")
    print(f"  Without ping: {dict(no_ping_actions)}")

    # ─── Sample actionable results ───
    print()
    print("─── Sample BUY Parses (first 10) ───")
    buy_count = 0
    for r in results:
        for pr in r["parsed"]:
            if pr.get("action") == "buy" and buy_count < 10:
                print(f"  MSG: {r['content'][:80]}")
                print(f"  → {json.dumps(pr, default=str)}")
                print()
                buy_count += 1

    print("─── Sample EXIT Parses (first 5) ───")
    exit_count = 0
    for r in results:
        for pr in r["parsed"]:
            if pr.get("action") == "exit" and exit_count < 5:
                print(f"  MSG: {r['content'][:80]}")
                if r["is_reply"] == "True":
                    print(f"  REPLY TO: {r['reply_to_content'][:80]}")
                print(f"  → {json.dumps(pr, default=str)}")
                print()
                exit_count += 1

    # ─── Errors ───
    if errors:
        print(f"─── Errors ({len(errors)}) ───")
        for e in errors[:10]:
            print(f"  [{e['idx']}] {e['content'][:80]}")
            print(f"  Error: {e['error']}")
            print()

    # ─── Save full results ───
    output = {
        "summary": {
            "total_messages": total,
            "parsed": len(results),
            "skipped": skipped,
            "api_calls": api_calls,
            "errors": len(errors),
            "elapsed_seconds": round(elapsed, 1),
            "avg_latency_ms": round(total_latency / api_calls) if api_calls else 0,
            "action_counts": dict(action_counts)
        },
        "results": results,
        "errors": errors
    }
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nFull results saved to {OUTPUT_PATH}")

if __name__ == "__main__":
    run_backtest()
