#!/usr/bin/env python3
"""Test IanParser against scraped messages with full context."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
import json
import asyncio
import time
import logging
from datetime import datetime, timezone
from collections import defaultdict
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

from channels.ian import IanParser
from config import CHANNELS_CONFIG

# Setup logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('ian_test')

# Test configuration
NUM_MESSAGES = 200
CONTEXT_WINDOW = 10  # Last 10 messages for context

def load_messages(csv_path: str) -> list:
    """Load messages from CSV."""
    messages = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            messages.append(row)
    return messages

def build_message_history(messages: list, current_idx: int, window: int) -> list:
    """Build message history context (last N messages before current)."""
    history = []
    start_idx = max(0, current_idx - window)
    for i in range(start_idx, current_idx):
        msg = messages[i]
        ts = msg.get('timestamp', '')
        try:
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            time_str = dt.strftime('%H:%M:%S')
        except:
            time_str = '00:00:00'
        content = msg.get('content', '')[:200]  # Truncate long messages
        if content:
            history.append(f"[{time_str}] {content}")
    return history

def build_message_meta(msg: dict) -> tuple | str:
    """Build message meta tuple (content, reply_context) or just content."""
    content = msg.get('content', '')
    is_reply = msg.get('is_reply', 'False') == 'True'
    reply_content = msg.get('reply_to_content', '')
    is_forward = msg.get('is_forward', 'False') == 'True'
    forward_content = msg.get('forward_content', '')

    # Build context
    context = None
    if is_reply and reply_content and reply_content != '[Could not fetch]':
        context = reply_content
    elif is_forward and forward_content:
        context = forward_content

    if context:
        return (content, context)
    return content

def test_parser():
    """Run parser test on last N messages."""
    print(f"=== IanParser Test - Last {NUM_MESSAGES} Messages ===\n")

    # Load messages
    csv_path = os.path.join(os.path.dirname(__file__), 'ian_raw_messages.csv')
    all_messages = load_messages(csv_path)
    print(f"Loaded {len(all_messages)} total messages")

    # Get last N messages
    test_messages = all_messages[-NUM_MESSAGES:]
    print(f"Testing last {len(test_messages)} messages\n")

    # Initialize parser
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    config = CHANNELS_CONFIG.get('Ian', {})
    config['name'] = 'Ian'  # Required by BaseParser
    parser = IanParser(
        openai_client=client,
        channel_id=1457490555016839289,
        config=config
    )

    # Stats tracking
    stats = {
        'total': 0,
        'actions': defaultdict(int),
        'errors': 0,
        'parse_times': [],
        'with_context': 0,
        'with_reply': 0,
    }

    results = []

    for i, msg in enumerate(test_messages):
        stats['total'] += 1
        msg_id = msg.get('message_id', 'unknown')
        content = msg.get('content', '')

        # Skip empty messages
        if not content.strip():
            stats['actions']['empty'] += 1
            continue

        # Build context
        global_idx = len(all_messages) - NUM_MESSAGES + i
        history = build_message_history(all_messages, global_idx, CONTEXT_WINDOW)
        message_meta = build_message_meta(msg)

        if isinstance(message_meta, tuple):
            stats['with_reply'] += 1
        if history:
            stats['with_context'] += 1

        # Parse message
        start_time = time.time()
        try:
            # Get received timestamp from message
            ts = msg.get('timestamp', '')
            try:
                received_ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            except:
                received_ts = datetime.now(timezone.utc)

            parsed, latency = parser.parse_message(
                message_meta=message_meta,
                received_ts=received_ts,
                logger=logger.info,
                message_history=history
            )
            parse_time = time.time() - start_time
            stats['parse_times'].append(parse_time)

            # Track actions
            if parsed:
                for entry in parsed:
                    action = entry.get('action', 'unknown')
                    stats['actions'][action] += 1

                    # Log non-null actions
                    if action != 'null':
                        results.append({
                            'msg_id': msg_id,
                            'content': content[:100],
                            'action': action,
                            'parsed': entry,
                            'parse_time': parse_time
                        })
            else:
                stats['actions']['null'] += 1

        except Exception as e:
            stats['errors'] += 1
            print(f"  ERROR on msg {msg_id}: {e}")

        # Progress indicator
        if (i + 1) % 20 == 0:
            print(f"  Processed {i + 1}/{len(test_messages)} messages...")

    # Print results
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)

    print(f"\nTotal messages tested: {stats['total']}")
    print(f"Messages with reply context: {stats['with_reply']}")
    print(f"Messages with history context: {stats['with_context']}")
    print(f"Errors: {stats['errors']}")

    print(f"\nAction Distribution:")
    for action, count in sorted(stats['actions'].items(), key=lambda x: -x[1]):
        pct = count / stats['total'] * 100
        print(f"  {action}: {count} ({pct:.1f}%)")

    if stats['parse_times']:
        avg_time = sum(stats['parse_times']) / len(stats['parse_times'])
        max_time = max(stats['parse_times'])
        min_time = min(stats['parse_times'])
        print(f"\nParse Time Stats:")
        print(f"  Average: {avg_time*1000:.0f}ms")
        print(f"  Min: {min_time*1000:.0f}ms")
        print(f"  Max: {max_time*1000:.0f}ms")

    print(f"\n{'=' * 60}")
    print("ACTIONABLE ALERTS FOUND")
    print("=" * 60)

    for r in results:
        action = r['action']
        parsed = r['parsed']
        content = r['content']

        if action == 'buy':
            ticker = parsed.get('ticker', '?')
            strike = parsed.get('strike', '?')
            opt_type = parsed.get('type', '?')
            price = parsed.get('price', '?')
            size = parsed.get('size', 'full')
            print(f"\n[BUY] {ticker} {strike}{opt_type[0] if opt_type else '?'} @ ${price} ({size})")
            print(f"  Content: {content}...")

        elif action == 'trim':
            ticker = parsed.get('ticker', '?')
            price = parsed.get('price', '?')
            print(f"\n[TRIM] {ticker} @ ${price}")
            print(f"  Content: {content}...")

        elif action == 'exit':
            ticker = parsed.get('ticker', '?')
            price = parsed.get('price', '?')
            print(f"\n[EXIT] {ticker} @ ${price}")
            print(f"  Content: {content}...")

        elif action == 'stop_update':
            ticker = parsed.get('ticker', '?')
            new_stop = parsed.get('new_stop', '?')
            print(f"\n[STOP_UPDATE] {ticker} -> {new_stop}")
            print(f"  Content: {content}...")

    # Save detailed results
    output_path = os.path.join(os.path.dirname(__file__), 'ian_parser_test_results.json')
    with open(output_path, 'w') as f:
        json.dump({
            'stats': {
                'total': stats['total'],
                'actions': dict(stats['actions']),
                'errors': stats['errors'],
                'avg_parse_time_ms': sum(stats['parse_times']) / len(stats['parse_times']) * 1000 if stats['parse_times'] else 0
            },
            'actionable_results': results
        }, f, indent=2, default=str)
    print(f"\nDetailed results saved to: {output_path}")

if __name__ == '__main__':
    test_parser()
